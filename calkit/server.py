"""A local server for interacting with project repos."""

import os

import dvc
import git
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

import calkit

app = FastAPI(title="calkit-server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Allow localhost and Calkit website only?
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


@app.get("/cwd")
def get_cwd() -> str:
    return os.getcwd()


@app.get("/ls")
def get_ls(dir: str = ".") -> list[dict]:
    repo = git.Repo()
    contents = os.listdir(dir)
    resp = []
    for item in contents:
        if item == ".git" or repo.ignored(item):
            continue
        if os.path.isfile(os.path.join(dir, item)):
            kind = "file"
        else:
            kind = "dir"
        resp.append(dict(name=item, type=kind))
    return sorted(resp, key=lambda item: (item["type"], item["name"]))


@app.post("/git/{command}")
def run_git_command(command: str, params: dict = {}):
    func = getattr(git.Repo().git, command)
    return func(**params)


@app.get("/diff")
def get_diff():
    """Get differences in working directory, from both Git and DVC."""
    pass


@app.get("/status")
def get_status():
    """Get status in working directory, from both Git and DVC."""
    git_repo = git.Repo()
    untracked_git_files = git_repo.untracked_files
    # Get a list of diffs of the working tree to the index
    git_diff = git_repo.index.diff(None)
    git_diff_files = [d.a_path for d in git_diff]
    dvc_repo = dvc.repo.Repo()
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
    # TODO: Structure this in an intelligent way and return something


@app.post("/open/vscode")
def open_vscode() -> int:
    return os.system("code .")


@app.get("/jupyter/servers")
def get_jupyter_servers() -> list[calkit.jupyter.Server]:
    return calkit.jupyter.get_servers()
