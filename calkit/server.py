"""A local server for interacting with project repos."""

import os
import subprocess

import dvc
import git
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

app = FastAPI(title="calkit-server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Only allow localhost and calkit.io?
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def get_health() -> str:
    return "All good!"


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
