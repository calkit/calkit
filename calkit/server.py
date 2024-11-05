"""A local server for interacting with project repos."""

from __future__ import annotations

import logging
import os
import re
import subprocess

import dvc
import dvc.config
import dvc.repo
import dvc.repo.data
import dvc.repo.status
import git
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

import platform

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
def get_root() -> list[LocalProject]:
    """Return information about the current running server.

    - The project owner
    - The project name
    - The current working directory
    - A Jupyter server running here, if applicable
    """
    resp = []
    project_dirs = calkit.find_project_dirs()
    servers = calkit.jupyter.get_servers()
    for pdir in project_dirs:
        try:
            project = calkit.git.detect_project_name(path=pdir)
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
def get_local_project(owner_name: str, project_name: str) -> LocalProject:
    all_projects = get_root()
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


@app.get("/diff")
def get_diff():
    """Get differences in working directory, from both Git and DVC."""
    raise HTTPException(501)


class Status(BaseModel):
    dvc: dict | None
    git: dict
    errors: list[dict] | None = None


@app.get("/projects/{owner_name}/{project_name}/status")
def get_status(owner_name: str, project_name: str):
    """Get status in working directory, from both Git and DVC."""
    errors = []
    logger.info(f"Looking for project {owner_name}/{project_name}")
    project = get_local_project(owner_name, project_name)
    logger.info(f"Found project at {project.wdir}")
    git_repo = git.Repo(project.wdir)
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
        dvc_data_status = dvc.repo.data.status(
            dvc_repo, not_in_remote=True, remote_refresh=True
        )
        dvc_status = dict(pipeline=dvc_pipeline_status, data=dvc_data_status)
    except dvc.config.ConfigError as e:
        errors.append(dict(type="dvc.config.ConfigError", info=str(e)))
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
    if req.commit:
        git_repo.git.add(".gitignore")
        if req.commit_message is None:
            msg = f"Add {path} to gitignore"
        else:
            msg = req.commit_message
        git_repo.git.commit(["-m", msg])
    if req.push:
        git_repo.git.push(["origin", git_repo.active_branch.name])
    return Message("Success!")


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
    subprocess.call(["calkit", "run"], cwd=project.wdir)
    return Message(message="Success!")


class Pipeline(BaseModel):
    raw_yaml: str | None = None
    stages: dict


@app.get("/projects/{owner_name}/{project_name}/pipeline")
def get_pipeline(owner_name: str, project_name: str) -> Pipeline:
    project = get_local_project(owner_name, project_name)
    fpath = os.path.join(project.wdir, "dvc.yaml")
    if os.path.isfile(fpath):
        with open(fpath) as f:
            raw_yaml = f.read()
        pipeline = calkit.ryaml.load(raw_yaml)
        return Pipeline(raw_yaml=raw_yaml, stages=pipeline.get("stages", {}))
    return Pipeline(raw_yaml=None, stages={})


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
