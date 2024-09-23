"""A local server for interacting with project repos."""

from __future__ import annotations

import os

import dvc
import dvc.repo
import git
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

import calkit
import calkit.jupyter

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
        project = calkit.git.detect_project_name(path=pdir)
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


@app.get("/diff")
def get_diff():
    """Get differences in working directory, from both Git and DVC."""
    raise HTTPException(501)


@app.get("/projects/{owner_name}/{project_name}/status")
def get_status(owner_name: str, project_name: str):
    """Get status in working directory, from both Git and DVC."""
    project = get_local_project(owner_name, project_name)
    git_repo = git.Repo(project.wdir)
    untracked_git_files = git_repo.untracked_files
    # Get a list of diffs of the working tree to the index
    git_diff = git_repo.index.diff(None)
    git_diff_files = [d.a_path for d in git_diff]
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
    dvc_status = dvc.repo.status.status(dvc_repo)
    # TODO: Structure this in an intelligent way
    return {
        "dvc": dvc_status,
        "git": {"untracked": untracked_git_files, "diff": git_diff_files},
    }


@app.post("/projects/{owner_name}/{project_name}/open/vscode")
def open_vscode(owner_name: str, project_name: str) -> int:
    project = get_local_project(owner_name, project_name)
    return os.system(f"code {project.wdir}")


@app.get("/jupyter/servers")
def get_jupyter_servers() -> list[calkit.jupyter.Server]:
    return calkit.jupyter.get_servers()
