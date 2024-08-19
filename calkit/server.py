"""A local server for interacting with project repos."""

import os

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


@app.post("/git/{command}")
def run_git_command(command: str, params: dict = {}):
    func = getattr(git.Repo().git, command)
    return func(**params)
