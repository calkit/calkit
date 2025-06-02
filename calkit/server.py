"""A local server for interacting with project repos."""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import sys
from typing import Literal

import dvc
import dvc.config
import dvc.repo
import dvc.repo.data
import dvc.repo.status
import git
from dvc.exceptions import NotDvcRepoError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

import calkit
import calkit.jupyter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__package__)

app = FastAPI(title="calkit-server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost",
        "https://calkit.io",
        "https://staging.calkit.io",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    message: str


@app.get("/health")
def get_health() -> str:
    return "All good!"


class LocalProject(BaseModel):
    owner_name: str
    project_name: str
    wdir: str
    jupyter_url: str | None
    jupyter_token: str | None


@app.get("/")
def get_root(get_jupyter_servers: bool = True) -> list[LocalProject]:
    """Return information about the current running server.

    - The project owner
    - The project name
    - The current working directory
    - A Jupyter server running here, if applicable
    """
    resp = []
    logger.info("Finding project directories")
    project_dirs = calkit.find_project_dirs()
    if get_jupyter_servers:
        logger.info("Getting Jupyter servers")
        servers = calkit.jupyter.get_servers()
    else:
        servers = []
    for pdir in project_dirs:
        logger.info(f"Inspecting {pdir}")
        try:
            project = calkit.detect_project_name(wdir=pdir)
        except ValueError:
            logger.warning(f"Can't detect project name in {pdir}")
            continue
        owner, name = project.split("/")
        url = token = None
        for server in servers:
            if server.wdir == pdir:
                url = server.url
                token = server.token
                break
        resp.append(
            LocalProject(
                owner_name=owner,
                project_name=name,
                wdir=os.path.abspath(pdir),
                jupyter_token=token,
                jupyter_url=url,
            )
        )
    return resp


@app.get("/projects/{owner_name}/{project_name}")
def get_local_project(
    owner_name: str, project_name: str, get_jupyter_server: bool = True
) -> LocalProject:
    all_projects = get_root(get_jupyter_servers=get_jupyter_server)
    for project in all_projects:
        if (
            project.owner_name == owner_name
            and project.project_name == project_name
        ):
            return project
    raise HTTPException(404)


@app.get("/projects/{owner_name}/{project_name}/jupyter-server")
def get_project_jupyter_server(
    owner_name: str,
    project_name: str,
    autostart=False,
    no_browser=False,
) -> calkit.jupyter.Server | None:
    project = get_local_project(
        owner_name=owner_name, project_name=project_name
    )
    if project is None:
        return
    if project.jupyter_url is not None:
        return calkit.jupyter.Server(
            url=project.jupyter_url,
            token=project.jupyter_token,
            wdir=project.wdir,
        )
    if autostart:
        calkit.jupyter.start_server(project.wdir, no_browser=no_browser)
        servers = calkit.jupyter.get_servers()
        for server in servers:
            if server.wdir == project.wdir:
                return server


@app.delete("/projects/{owner_name}/{project_name}/jupyter-server")
def stop_project_jupyter_server(owner_name: str, project_name: str) -> None:
    project = get_local_project(
        owner_name=owner_name, project_name=project_name
    )
    if project is None:
        return
    if project.jupyter_url is not None:
        calkit.jupyter.stop_server(url=project.jupyter_url)


@app.get("/cwd")
def get_cwd() -> str:
    return os.getcwd()


@app.get("/projects/{owner_name}/{project_name}/ls")
def get_ls(owner_name: str, project_name: str) -> list[dict]:
    project = get_local_project(owner_name, project_name)
    repo = git.Repo(project.wdir)
    contents = os.listdir(project.wdir)
    resp = []
    for item in contents:
        if item == ".git" or repo.ignored(item):
            continue
        if os.path.isfile(os.path.join(project.wdir, item)):
            kind = "file"
        else:
            kind = "dir"
        resp.append(dict(name=item, type=kind))
    return sorted(resp, key=lambda item: (item["type"], item["name"]))


@app.post("/projects/{owner_name}/{project_name}/git/{command}")
def run_git_command(
    owner_name: str, project_name: str, command: str, params: dict = {}
):
    project = get_local_project(owner_name, project_name)
    func = getattr(git.Repo(project.wdir).git, command)
    return func(**params)


class GitPushPost(BaseModel):
    remote_name: str = "origin"
    branch_name: str | None = None


@app.post("/projects/{owner_name}/{project_name}/git/push")
def git_push(owner_name: str, project_name: str, req: GitPushPost) -> Message:
    logger.info(f"Looking for project {owner_name}/{project_name}")
    project = get_local_project(owner_name, project_name)
    logger.info(f"Found project at {project.wdir}")
    git_repo = git.Repo(project.wdir)
    branch_name = req.branch_name | git_repo.active_branch.name
    logger.info(f"Git pushing to {req.remote_name} {branch_name}")
    git_repo.git.push(
        [req.remote_name, req.branch_name | git_repo.active_branch.name]
    )
    return Message(message="Success!")


@app.post("/projects/{owner_name}/{project_name}/git/pull")
def git_pull(owner_name: str, project_name: str) -> Message:
    logger.info(f"Looking for project {owner_name}/{project_name}")
    project = get_local_project(owner_name, project_name)
    logger.info(f"Found project at {project.wdir}")
    git_repo = git.Repo(project.wdir)
    git_repo.git.pull("--ff-only")
    return Message(message="Success!")


@app.post("/projects/{owner_name}/{project_name}/dvc/pull")
def dvc_pull(owner_name: str, project_name: str) -> Message:
    logger.info(f"Looking for project {owner_name}/{project_name}")
    project = get_local_project(owner_name, project_name)
    logger.info(f"Found project at {project.wdir}")
    subprocess.check_call(
        [sys.executable, "-m", "dvc", "pull"], cwd=project.wdir
    )
    return Message(message="Success!")


@app.post("/projects/{owner_name}/{project_name}/dvc/push")
def dvc_push(owner_name: str, project_name: str) -> Message:
    logger.info(f"Looking for project {owner_name}/{project_name}")
    project = get_local_project(owner_name, project_name)
    logger.info(f"Found project at {project.wdir}")
    subprocess.check_call(
        [sys.executable, "-m", "dvc", "push"], cwd=project.wdir
    )
    return Message(message="Success!")


@app.get("/diff")
def get_diff():
    """Get differences in working directory, from both Git and DVC."""
    raise HTTPException(501)


class Status(BaseModel):
    dvc: dict | None
    git: dict
    errors: list[dict] | None = None


@app.get("/projects/{owner_name}/{project_name}/status")
def get_status(
    owner_name: str,
    project_name: str,
    fetch_git: bool = True,
    fetch_dvc: bool = True,
):
    """Get status in working directory, from both Git and DVC."""
    errors = []
    logger.info(f"Looking for project {owner_name}/{project_name}")
    project = get_local_project(
        owner_name, project_name, get_jupyter_server=False
    )
    logger.info(f"Found project at {project.wdir}")
    git_repo = git.Repo(project.wdir)
    if fetch_git:
        git_repo.git.fetch()
    untracked_git_files = git_repo.untracked_files
    # Get a list of diffs of the working tree to the index
    git_diff = git_repo.index.diff(None)
    git_diff_files = [d.a_path for d in git_diff]
    git_staged = git_repo.index.diff("HEAD")
    git_staged_files = [d.a_path for d in git_staged]
    # See if we're ahead and/or behind origin remote
    # From https://stackoverflow.com/a/52757014/2284865
    ahead = 0
    behind = 0
    # Porcelain v2 is easier to parse, branch shows ahead/behind
    repo_status = git_repo.git.status(porcelain="v2", branch=True)
    ahead_behind_match = re.search(
        r"#\sbranch\.ab\s\+(\d+)\s-(\d+)", repo_status
    )
    # If no remotes exist or the HEAD is detached, there is no ahead/behind
    if ahead_behind_match:
        ahead = int(ahead_behind_match.group(1))
        behind = int(ahead_behind_match.group(2))
    # If the DVC remote is not configured properly, we might raise a
    # dvc.config.ConfigError here
    try:
        dvc_repo = dvc.repo.Repo(project.wdir)
        # Get a dictionary of DVC artifacts that have changed, keyed by the DVC
        # file, where values are a list, which may include a dict with a
        # 'changed outs' key, e.g.,
        # {
        #     "data/jhtdb-transitional-bl/all-stats.h5.dvc": [
        #         {
        #             "changed outs": {
        #                 "data/jhtdb-transitional-bl/all-stats.h5": "modified"
        #             }
        #         }
        #     ]
        # }
        dvc_pipeline_status = dvc.repo.status.status(dvc_repo)
        # Remove any always changed entries so the pipeline doesn't look
        # out of date
        logger.info(f"Raw DVC pipeline status: {dvc_pipeline_status}")
        dvc_pipeline_status = {
            k.split("dvc.yaml:")[-1]: v
            for k, v in dvc_pipeline_status.items()
            if v != ["always changed"] and not k.endswith(".dvc")
        }
        logger.info(
            f"DVC pipeline status after filtering: {dvc_pipeline_status}"
        )
        dvc_data_status = dvc.repo.data.status(
            dvc_repo, not_in_remote=fetch_dvc, remote_refresh=fetch_dvc
        )
        # Reformat this a bit, since it can be a little hard to understand
        # DVC calls a path committed when its DVC file is staged
        dvc_data_status["changed"] = dvc_data_status.get(
            "uncommitted", {}
        ).get("modified", [])
        dvc_data_status["staged"] = dvc_data_status.get("committed", {}).get(
            "modified", []
        )
        dvc_status = dict(pipeline=dvc_pipeline_status, data=dvc_data_status)
    except (dvc.config.ConfigError, NotDvcRepoError) as e:
        errors.append(dict(type=str(type(e)), info=str(e)))
        dvc_status = None
    # TODO: Structure this in an intelligent way
    return {
        "dvc": dvc_status,
        "git": {
            "untracked": untracked_git_files,
            "changed": git_diff_files,
            "staged": git_staged_files,
            "commits_ahead": ahead,
            "commits_behind": behind,
        },
        "errors": errors,
    }


class GitIgnorePut(BaseModel):
    path: str
    commit: bool = True
    commit_message: str | None = None
    push: bool = False


@app.put("/projects/{owner_name}/{project_name}/git/ignored")
def put_git_ignored(
    owner_name: str, project_name: str, req: GitIgnorePut
) -> Message:
    project = get_local_project(owner_name, project_name)
    git_repo = git.Repo(project.wdir)
    path = req.path
    if git_repo.ignored(path):
        logger.info(f"{path} is already ignored")
        return Message(message=f"{path} is already ignored")
    ignore_fpath = os.path.join(git_repo.working_dir, ".gitignore")
    if os.path.isfile(ignore_fpath):
        with open(ignore_fpath) as f:
            txt = f.read()
    else:
        txt = ""
    txt += "\n" + path + "\n"
    with open(ignore_fpath, "w") as f:
        f.write(txt)
    if req.commit and git_repo.git.diff():
        git_repo.git.add(".gitignore")
        if req.commit_message is None:
            msg = f"Add {path} to gitignore"
        else:
            msg = req.commit_message
        git_repo.git.commit(["-m", msg])
    if req.push:
        git_repo.git.push(["origin", git_repo.active_branch.name])
    return Message(message="Success!")


class AddPost(BaseModel):
    paths: list[str]
    to: Literal["git", "dvc"] | None = None
    commit: bool = True
    commit_message: str | None = None
    push: bool = False


@app.post("/projects/{owner_name}/{project_name}/calkit/add")
def calkit_add(owner_name: str, project_name: str, req: AddPost) -> Message:
    project = get_local_project(owner_name, project_name)
    cmd = ["calkit", "add"] + req.paths
    paths_txt = ", ".join(req.paths)
    if req.commit:
        msg = req.commit_message
        if msg is None:
            msg = f"Add {paths_txt}"
        cmd += ["--commit-message", msg]
    if req.to is not None:
        cmd += ["--to", req.to]
    if req.push:
        cmd += ["--push"]
    try:
        subprocess.call(cmd, cwd=project.wdir)
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, f"Failed to run {cmd}: {e}")
    return Message(message=f"Added paths: {paths_txt}")


class CommitPost(BaseModel):
    paths: list[str]
    to: Literal["git", "dvc"] | None = None
    commit_message: str | None = None
    push: bool = False


@app.post("/projects/{owner_name}/{project_name}/calkit/add-and-commit")
def calkit_add_and_commit(
    owner_name: str, project_name: str, req: AddPost
) -> Message:
    project = get_local_project(owner_name, project_name)
    git_repo = git.Repo(project.wdir)
    # Unstage any staged files since we're going to add and commit here
    git_repo.git.reset()
    cmd = ["calkit", "add"] + req.paths
    paths_txt = ", ".join(req.paths)
    msg = req.commit_message
    if msg is None:
        msg = f"Update {paths_txt}"
    cmd += ["--commit-message", msg]
    if req.to is not None:
        cmd += ["--to", req.to]
    if req.push:
        cmd += ["--push"]
    try:
        subprocess.call(cmd, cwd=project.wdir)
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, f"Failed to run {cmd}: {e}")
    return Message(message=f"Added and committed paths: {paths_txt}")


@app.post("/projects/{owner_name}/{project_name}/actions/discard-changes")
def discard_changes(owner_name: str, project_name: str) -> Message:
    project = get_local_project(owner_name, project_name)
    git_repo = git.Repo(project.wdir)
    # Stash any git changes
    git_repo.git.stash()
    # Checkout any DVC changes
    # If the DVC remote is not configured properly, we might raise a
    # dvc.config.ConfigError here
    try:
        dvc_repo = dvc.repo.Repo(project.wdir)
        dvc_data_status = dvc.repo.data.status(dvc_repo)
        # Get only the changed files since anything will be uncommitted after
        # the git stash
        changed = dvc_data_status.get("uncommitted", {}).get("modified", [])
        for path in changed:
            logger.info(f"Checking out {path} with DVC")
            subprocess.check_call(
                [sys.executable, "-m", "dvc", "checkout", path, "--force"],
                cwd=project.wdir,
            )
    except dvc.config.ConfigError:
        pass
    return Message(message="Changes successfully discarded")


@app.post("/projects/{owner_name}/{project_name}/open/vscode")
def open_vscode(owner_name: str, project_name: str) -> int:
    project = get_local_project(owner_name, project_name)
    return os.system(f"code {project.wdir}")


@app.get("/jupyter/servers")
def get_jupyter_servers() -> list[calkit.jupyter.Server]:
    return calkit.jupyter.get_servers()


@app.post("/projects/{owner_name}/{project_name}/pipeline/runs")
def run_pipeline(owner_name: str, project_name: str) -> Message:
    project = get_local_project(owner_name, project_name)
    try:
        subprocess.check_call(["calkit", "run"], cwd=project.wdir)
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, f"Pipeline failed to run: {e}")
    return Message(message="Success!")


class Pipeline(BaseModel):
    raw_yaml: str | None = None
    stages: dict
    mermaid: str | None = None


@app.get("/projects/{owner_name}/{project_name}/pipeline")
def get_pipeline(owner_name: str, project_name: str) -> Pipeline:
    project = get_local_project(owner_name, project_name)
    fpath = os.path.join(project.wdir, "dvc.yaml")
    if os.path.isfile(fpath):
        with open(fpath) as f:
            raw_yaml = f.read()
        pipeline = calkit.ryaml.load(raw_yaml)
        mermaid = subprocess.check_output(
            [sys.executable, "-m", "dvc", "dag", "--mermaid"], cwd=project.wdir
        ).decode()
        return Pipeline(
            raw_yaml=raw_yaml,
            stages=pipeline.get("stages", {}),
            mermaid=mermaid,
        )
    return Pipeline(raw_yaml=None, stages={}, mermaid=None)


class StageObject(BaseModel):
    title: str
    description: str


class StagePost(BaseModel):
    name: str
    cmd: str
    deps: list[str] | None
    outs: list[str] | None
    calkit_type: Literal["figure", "dataset", "publication"] | None = None
    calkit_object: StageObject | None = None
    commit: bool = True
    push: bool = False


@app.post("/projects/{owner_name}/{project_name}/pipeline/stages")
def post_pipeline_stage(
    owner_name: str, project_name: str, req: StagePost
) -> Message:
    project = get_local_project(owner_name, project_name)
    dvc_fpath = os.path.join(project.wdir, "dvc.yaml")
    if req.calkit_type is not None and req.calkit_object is None:
        raise HTTPException(422, "Calkit object info must be provided")
    if req.calkit_type is not None:
        if req.outs is None or len(req.outs) != 1:
            raise HTTPException(400, "One output must be provided")
    if os.path.isfile(dvc_fpath):
        with open(dvc_fpath) as f:
            pipeline = calkit.ryaml.load(f)
    else:
        pipeline = {}
    stages = pipeline.get("stages", {})
    stage_names = list(stages.keys())
    if req.name in stage_names:
        raise HTTPException(
            400, "Stage with same name already exists in pipeline"
        )
    # Make sure we don't have any conflicting outputs
    all_outs = []
    for _, stage in stages.items():
        all_outs += stage.get("outs", [])
    if req.outs is not None:
        for out in req.outs:
            if out in all_outs:
                raise HTTPException(
                    400, "Output is already part of another stage"
                )
    new_stage = dict(cmd=req.cmd)
    if req.deps:
        new_stage["deps"] = req.deps
    if req.outs:
        new_stage["outs"] = req.outs
    stages[req.name] = new_stage
    pipeline["stages"] = stages
    with open(dvc_fpath, "w") as f:
        calkit.ryaml.dump(pipeline, f)
    repo = git.Repo(path=project.wdir)
    repo.git.add("dvc.yaml")
    # Add Calkit object if applicable
    if req.calkit_type is not None:
        ck_info = calkit.load_calkit_info(wdir=project.wdir)
        ck_objs = ck_info.get(req.calkit_type + "s", [])
        existing_paths = [obj.get("path") for obj in ck_objs]
        out = req.outs[0]
        if out in existing_paths:
            raise HTTPException(
                400, f"{req.calkit_type} already exists at {out}"
            )
        new_obj = (
            dict(path=out, stage=req.name) | req.calkit_object.model_dump()
        )
        ck_objs.append(new_obj)
        ck_info[req.calkit_type + "s"] = ck_objs
        with open(os.path.join(project.wdir, "calkit.yaml"), "w") as f:
            calkit.ryaml.dump(ck_info, f)
        repo.git.add("calkit.yaml")
    if req.commit:
        repo.git.commit(["-m", f"Add new pipeline stage {req.name}"])
    if req.push:
        repo.git.push(["origin", repo.active_branch.name])
    return Message(message="Successfully added stage")


@app.post("/projects/{owner_name}/{project_name}/open/folder")
def open_folder(owner_name: str, project_name: str) -> Message:
    project = get_local_project(owner_name, project_name)
    if platform.system() == "Windows":
        cmd = ["explorer"]
    else:
        cmd = ["open"]
    cmd.append(project.wdir)
    subprocess.Popen(cmd, cwd=project.wdir)
    return Message(message=f"Opened {project.wdir} with `{cmd[0]}`")


class ClonePost(BaseModel):
    git_repo_url: str
    protocol: Literal["https", "ssh"] = "https"


@app.post("/calkit/clone")
def clone_repo(req: ClonePost) -> Message:
    parent_dir = os.path.join(os.path.expanduser("~"), "calkit")
    os.makedirs(parent_dir, exist_ok=True)
    dest_dir = req.git_repo_url.split("/")[-1].removesuffix(".git")
    abs_dest_dir = os.path.join(parent_dir, dest_dir)
    if os.path.exists(abs_dest_dir):
        raise HTTPException(400, "Destination directory already exists")
    if req.protocol == "ssh":
        url = req.git_repo_url.replace(
            "https://github.com/", "git@github.com:"
        )
    else:
        url = req.git_repo_url
    if not url.endswith(".git"):
        url += ".git"
    cmd = ["calkit", "clone", url]
    try:
        subprocess.call(cmd, cwd=parent_dir)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to clone: {e}")
        raise HTTPException(500, f"Failed to clone: {e}")
    return Message(message=f"Successfully cloned into {abs_dest_dir}")
