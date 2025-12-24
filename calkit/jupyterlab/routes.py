"""JupyterLab extension server routes."""

import glob
import json
import os
import subprocess
import sys

import dvc
import dvc.repo
import git
import tornado
from dvc.exceptions import NotDvcRepoError
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
from pydantic import BaseModel

import calkit
from calkit.cli.new import (
    new_conda_env,
    new_julia_env,
    new_pixi_env,
    new_uv_venv,
    new_venv,
)
from calkit.git import ensure_path_is_ignored


class HelloRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        self.finish(
            json.dumps(
                {
                    "data": (
                        "Hello, world!"
                        " This is the '/calkit/hello' endpoint."
                        " Try visiting me in your browser!"
                    )
                }
            )
        )


class ProjectRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        self.log.info(f"Received request for project info in {os.getcwd()}")
        self.finish(json.dumps(calkit.load_calkit_info()))

    @tornado.web.authenticated
    def put(self):
        """Update project metadata (name, title, description, git_repo_url)."""
        self.log.info("Received PUT request to update project info")
        body = self.get_json_body()
        if not body:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must be valid JSON"})
            )
            return
        ck_info = calkit.load_calkit_info(process_includes=False)
        # Update top-level fields from body
        for field in ["name", "title", "description", "git_repo_url", "owner"]:
            if field in body:
                ck_info[field] = body[field]
        # Write back to calkit.yaml
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        self.log.info("Updated project info successfully")
        self.finish(json.dumps(ck_info))


class KernelspecsRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        self.log.info("Received request for calkit kernelspec info")
        specs = ["sup", "lol", "hehe"]
        self.finish(json.dumps({"kernelspecs": specs}))


class Notebook(BaseModel):
    path: str
    environment: dict | None = None
    stage: dict | None = None
    notebook: dict | None = None


def get_notebook(path: str, ck_info: dict) -> dict | None:
    """Get notebook metadata for a given path.

    If the notebook doesn't exist, return None.
    """
    if not os.path.isfile(path):
        return None
    envs = ck_info.get("environments", {})
    stages = ck_info.get("pipeline", {}).get("stages", {})
    env_name = None
    stage_name = None
    stage_info = None
    # Notebook environment can either be specified in the notebook
    # or the pipeline stage
    # The latter is preferred since we want users to put their
    # notebooks into the pipeline so they don't need to run them
    # manually
    for sname, stage in stages.items():
        if (
            stage.get("kind") == "jupyter-notebook"
            and stage.get("notebook_path") == path
        ):
            env_name = stage.get("environment")
            stage_name = sname
            stage_info = stage
            break
    nb_info = None
    if not env_name:
        # Check if the notebook is in the notebooks section
        project_notebooks = ck_info.get("notebooks", [])
        for nb in project_notebooks:
            if nb.get("path") == path:
                env_name = nb.get("environment")
                nb_info = nb
                break
    env = dict(envs.get(env_name)) if env_name else None
    if env and env_name:
        env["name"] = env_name
    # Build stage object with all stage metadata
    stage = None
    if stage_info:
        stage = {
            "name": stage_name,
            "inputs": stage_info.get("inputs", []),
            "outputs": stage_info.get("outputs", []),
            "description": stage_info.get("description"),
        }
    return Notebook(
        path=path, environment=env, stage=stage, notebook=nb_info
    ).model_dump()


class NotebooksRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        """Get a list of notebooks or a specific notebook's info.

        If a path argument is provided, return info for that specific notebook.
        Otherwise, return a list of all notebooks in the project.
        """
        notebook_path = self.get_argument("path", "")
        self.log.info(
            f"NotebooksRouteHandler.get() called with path: '{notebook_path}'"
        )
        if notebook_path:
            # Return info for a specific notebook
            self.log.info(
                f"Received request for notebook info: {notebook_path}"
            )
            if not os.path.isfile(notebook_path):
                self.set_status(400)
                self.finish(
                    json.dumps(
                        {"error": f"Notebook not found: {notebook_path}"}
                    )
                )
                return
            ck_info = calkit.load_calkit_info()
            notebook = get_notebook(notebook_path, ck_info)
            self.finish(json.dumps(notebook))
        else:
            # Return list of all notebooks in the project
            self.log.info("Received request for calkit notebooks info")
            ck_info = calkit.load_calkit_info()
            resp = []
            # Search for notebooks up to 3 directories deep, but not under
            # .calkit or .ipynb_checkpoints
            nb_paths = glob.glob("**/*.ipynb", recursive=True)
            for nb_path in nb_paths:
                if ".calkit/" in nb_path or ".ipynb_checkpoints/" in nb_path:
                    continue
                resp.append(get_notebook(nb_path, ck_info=ck_info))
            self.finish(json.dumps(resp))

    @tornado.web.authenticated
    def post(self):
        """Add a notebook, and include if it exists."""
        body = self.get_json_body()
        if not body:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must be valid JSON"})
            )
            return
        notebook_path = body.get("path")
        if not notebook_path:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must include 'path'"})
            )
            return


class GitStatusRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        try:
            repo = git.Repo(os.getcwd())
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": f"Not a git repo: {e}"}))
            return
        changed = [
            item.a_path for item in repo.index.diff(None) if item.a_path
        ]
        staged = [
            item.a_path for item in repo.index.diff("HEAD") if item.a_path
        ]
        untracked = list(repo.untracked_files)
        try:
            tracked = list(
                {*changed, *staged, *repo.git.ls_files().splitlines()}
            )
        except Exception:
            tracked = list({*changed, *staged})
        sizes: dict[str, int] = {}
        for path in {
            **{p: None for p in changed},
            **{p: None for p in staged},
            **{p: None for p in untracked},
        }:
            try:
                sizes[path] = os.path.getsize(path)
            except Exception:
                continue
        ahead = 0
        behind = 0
        branch = None
        remote = None
        try:
            branch = repo.active_branch.name
            tracking = repo.active_branch.tracking_branch()
            if tracking is not None:
                remote = str(tracking)
                # Use --left-right to count ahead/behind
                commits = repo.git.rev_list(
                    "--left-right", f"{tracking}...HEAD"
                ).splitlines()
                for c in commits:
                    if c.startswith("<"):
                        behind += 1
                    elif c.startswith(">"):
                        ahead += 1
        except Exception:
            pass
        self.finish(
            json.dumps(
                {
                    "changed": changed,
                    "staged": staged,
                    "untracked": untracked,
                    "tracked": tracked,
                    "sizes": sizes,
                    "ahead": ahead,
                    "behind": behind,
                    "branch": branch,
                    "remote": remote,
                }
            )
        )


class PipelineStatusRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        try:
            dvc_repo = dvc.repo.Repo(os.getcwd())
            raw_status = dvc_repo.status()
            pipeline_status = {
                k.split("dvc.yaml:")[-1]: v
                for k, v in raw_status.items()
                if v != ["always changed"] and not k.endswith(".dvc")
            }
            is_outdated = len(pipeline_status) > 0
            self.finish(
                json.dumps(
                    {
                        "pipeline": pipeline_status,
                        "is_outdated": is_outdated,
                    }
                )
            )
        except NotDvcRepoError:
            self.finish(json.dumps({"pipeline": {}, "is_outdated": False}))
            return
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps(
                    {
                        "pipeline": {},
                        "is_outdated": False,
                        "error": f"Failed to get pipeline status: {e}",
                    }
                )
            )
            return


class GitIgnoreRouteHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        body = self.get_json_body() or {}
        paths = body.get("paths") or []
        if not isinstance(paths, list):
            self.set_status(400)
            self.finish(json.dumps({"error": "paths must be a list"}))
            return
        try:
            repo = git.Repo(os.getcwd())
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": f"Not a git repo: {e}"}))
            return
        for path in paths:
            try:
                ensure_path_is_ignored(repo, path)
            except Exception as e:
                self.set_status(500)
                self.finish(
                    json.dumps({"error": f"Failed to ignore {path}: {e}"})
                )
                return
        self.finish(json.dumps({"ok": True, "ignored": paths}))


class GitCommitRouteHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        body = self.get_json_body() or {}
        message = body.get("message", "")
        files = body.get("files", [])
        if not message:
            self.set_status(400)
            self.finish(json.dumps({"error": "Commit 'message' is required"}))
            return
        try:
            repo = git.Repo(os.getcwd())
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": f"Not a git repo: {e}"}))
            return
        staged_paths: list[str] = []
        for f in files:
            path = f.get("path")
            if not path:
                continue
            store_in_dvc = bool(f.get("store_in_dvc"))
            stage = f.get("stage", True)
            if store_in_dvc:
                try:
                    subprocess.check_call(
                        [sys.executable, "-m", "dvc", "add", path]
                    )
                    ensure_path_is_ignored(repo, path)
                    dvc_file = f"{path}.dvc"
                    if os.path.exists(dvc_file):
                        repo.git.add([dvc_file])
                        staged_paths.append(dvc_file)
                except Exception as e:
                    self.set_status(500)
                    self.finish(
                        json.dumps(
                            {"error": f"DVC add failed for {path}: {e}"}
                        )
                    )
                    return
            elif stage:
                try:
                    repo.git.add([path])
                    staged_paths.append(path)
                except Exception as e:
                    self.set_status(500)
                    self.finish(
                        json.dumps({"error": f"Failed to stage {path}: {e}"})
                    )
                    return
        try:
            if staged_paths:
                repo.index.commit(message)
            else:
                # Allow empty commit to just annotate state
                repo.git.commit(["--allow-empty", "-m", message])
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": f"Commit failed: {e}"}))
            return
        self.finish(json.dumps({"ok": True, "committed": staged_paths}))


class GitHistoryRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        try:
            repo = git.Repo(os.getcwd())
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": f"Not a git repo: {e}"}))
            return
        max_count = int(self.get_argument("max", "20"))
        commits = []
        for c in repo.iter_commits(max_count=max_count):
            commits.append(
                {
                    "hash": c.hexsha,
                    "message": c.message.strip(),
                    "author": str(c.author),
                    "date": c.committed_datetime.isoformat(),
                }
            )
        self.finish(json.dumps({"commits": commits}))


class GitPushRouteHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        try:
            repo = git.Repo(os.getcwd())
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": f"Not a git repo: {e}"}))
            return
        try:
            remote = repo.remotes[0]
        except Exception:
            self.set_status(400)
            self.finish(json.dumps({"error": "No git remote configured"}))
            return
        try:
            res = remote.push()
            messages = [str(r) for r in res]
            self.finish(json.dumps({"ok": True, "result": messages}))
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": f"Push failed: {e}"}))
            return


class EnvironmentsRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        self.log.info("Received request for calkit environments")
        # Parse params
        # Check params for notebook only environments filtering so we can
        # filter down for notebook-appropriate envs only
        notebook_only = self.get_argument("notebook_only", "0") == "1"
        ck_info = calkit.load_calkit_info()
        envs = dict(ck_info.get("environments", {}))
        if notebook_only:
            for env_name, env in list(envs.items()):
                if env.get("kind") not in [
                    "uv-venv",
                    "venv",
                    "pixi",
                    "renv",
                    "julia",
                    "conda",
                ]:
                    envs.pop(env_name)
        # Get package spec for env and return with it
        # TODO: Enable this for other kinds of envs
        for env_name, env in list(envs.items()):
            env_path = env.get("path")
            if (
                env.get("kind") in ["uv-venv", "venv"]
                and env_path
                and os.path.isfile(env_path)
            ):
                packages = []
                with open(env_path) as f:
                    for line in f.readlines():
                        line = line.strip().split("#")[0].strip()
                        if line:
                            packages.append(line)
                envs[env_name]["packages"] = packages
        self.finish(json.dumps({"environments": envs}))

    @tornado.web.authenticated
    def post(self):
        """Create a new environment."""
        body = self.get_json_body()
        if not body:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must be valid JSON"})
            )
            return
        env_name = body.get("name")
        env_kind = body.get("kind")
        env_path = body.get("path")
        packages = body.get("packages", [])
        if env_kind not in ["uv-venv", "venv", "pixi", "julia", "conda"]:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            f"Unsupported environment kind '{env_kind}'."
                            " Supported kinds are: uv-venv, venv, pixi,"
                            " julia, conda."
                        )
                    }
                )
            )
            return
        if not env_name or not env_kind or not env_path or not packages:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            "Request body must include 'name', 'kind',"
                            " 'path', and 'packages'"
                        )
                    }
                )
            )
            return
        # Use the Calkit CLI to create the environment
        func_to_kind = {
            "uv-venv": new_uv_venv,
            "venv": new_venv,
            "pixi": new_pixi_env,
            "julia": new_julia_env,
            "conda": new_conda_env,
        }
        try:
            func_to_kind[env_kind](
                name=env_name,
                path=env_path,
                packages=packages,
                no_commit=True,
            )
        except Exception as e:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            f"Failed to create environment '{env_name}': {e}"
                        )
                    }
                )
            )
            return
        self.log.info(f"Created new environment '{env_name}' successfully")
        self.finish(json.dumps({"message": "New environment created"}))


def setup_route_handlers(web_app):
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]
    handlers = [
        (url_path_join(base_url, "calkit", "hello"), HelloRouteHandler),
        (url_path_join(base_url, "calkit", "project"), ProjectRouteHandler),
        (
            url_path_join(base_url, "calkit", "kernelspecs"),
            KernelspecsRouteHandler,
        ),
        (
            url_path_join(base_url, "calkit", "notebooks"),
            NotebooksRouteHandler,
        ),
        (
            url_path_join(base_url, "calkit", "git", "status"),
            GitStatusRouteHandler,
        ),
        (
            url_path_join(base_url, "calkit", "pipeline", "status"),
            PipelineStatusRouteHandler,
        ),
        (
            url_path_join(base_url, "calkit", "git", "commit"),
            GitCommitRouteHandler,
        ),
        (
            url_path_join(base_url, "calkit", "git", "history"),
            GitHistoryRouteHandler,
        ),
        (
            url_path_join(base_url, "calkit", "git", "ignore"),
            GitIgnoreRouteHandler,
        ),
        (
            url_path_join(base_url, "calkit", "git", "push"),
            GitPushRouteHandler,
        ),
        (
            url_path_join(base_url, "calkit", "environments"),
            EnvironmentsRouteHandler,
        ),
    ]
    web_app.add_handlers(host_pattern, handlers)
