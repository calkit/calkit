"""JupyterLab extension server routes."""

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import dvc
import dvc.repo
import git
import tornado
from dvc.exceptions import NotDvcRepoError
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
from pydantic import BaseModel

import calkit
import calkit.cli.main
import calkit.pipeline
from calkit.cli.new import (
    new_conda_env,
    new_julia_env,
    new_pixi_env,
    new_uv_venv,
    new_venv,
)
from calkit.cli.notebooks import check_env_kernel
from calkit.git import ensure_path_is_ignored
from calkit.models.pipeline import JupyterNotebookStage


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
        notebook_title = body.get("title")
        notebook_description = body.get("description")
        notebook_env = body.get("environment")
        stage_name = body.get("stage")
        if not notebook_path:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must include 'path'"})
            )
            return
        self.log.info(f"Received request to add notebook: {notebook_path}")
        ck_info = calkit.load_calkit_info()
        if notebook_env and notebook_env not in ck_info.get(
            "environments", {}
        ):
            self.set_status(400)
            self.finish(
                {"error": f"Environment '{notebook_env}' does not exist"}
            )
            return
        # Create a directory for the notebook if necessary
        notebook_dir = os.path.dirname(notebook_path)
        if notebook_dir:
            os.makedirs(notebook_dir, exist_ok=True)
        notebook_path = Path(notebook_path).as_posix()
        nb_paths = [nb.get("path") for nb in ck_info.get("notebooks", [])]
        if notebook_path not in nb_paths:
            # Add notebook entry
            if "notebooks" not in ck_info:
                ck_info["notebooks"] = []
            nb = {
                "path": notebook_path,
                "title": notebook_title,
                "description": notebook_description,
            }
            if stage_name:
                nb["stage"] = stage_name
            elif notebook_env:
                nb["environment"] = notebook_env
            ck_info["notebooks"].append(nb)
            # Write back to calkit.yaml
            with open("calkit.yaml", "w") as f:
                calkit.ryaml.dump(ck_info, f)
            self.log.info(f"Added notebook '{notebook_path}' successfully")
        if stage_name:
            pipeline = ck_info.get("pipeline", {})
            existing_stages = pipeline.get("stages", {})
            if not notebook_env:
                self.set_status(400)
                self.finish(
                    json.dumps(
                        {"error": "Stage must have an environment defined"}
                    )
                )
                return
            if stage_name in existing_stages:
                self.set_status(400)
                self.finish(
                    json.dumps(
                        {"error": f"Stage '{stage_name}' already exists"}
                    )
                )
                return
            stage = {
                "kind": "jupyter-notebook",
                "notebook_path": notebook_path,
                "environment": notebook_env,
            }
            inputs = body.get("inputs", [])
            if inputs:
                stage["inputs"] = inputs
            outputs = body.get("outputs", [])
            if outputs:
                stage["outputs"] = outputs
            existing_stages[stage_name] = stage
            pipeline["stages"] = existing_stages
            ck_info["pipeline"] = pipeline
            with open("calkit.yaml", "w") as f:
                calkit.ryaml.dump(ck_info, f)
        self.finish(json.dumps(ck_info))


class NotebookEnvironmentRouteHandler(APIHandler):
    @tornado.web.authenticated
    def put(self):
        """Set the environment for a notebook."""
        body = self.get_json_body()
        if not body:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must be valid JSON"})
            )
            return
        notebook_path = body.get("path")
        environment_name = body.get("environment")
        if not notebook_path or not environment_name:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            "Request body must include 'path' and"
                            " 'environment'"
                        )
                    }
                )
            )
            return
        ck_info = calkit.load_calkit_info()
        envs = ck_info.get("environments", {})
        if environment_name not in envs:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            f"Environment '{environment_name}' does not exist"
                        )
                    }
                )
            )
        # First see if this notebook is part of a pipeline stage
        stages = ck_info.get("pipeline", {}).get("stages", {})
        for stage_name, stage_info in list(stages.items()):
            if (
                stage_info.get("kind") == "jupyter-notebook"
                and stage_info.get("notebook_path") == notebook_path
            ):
                # Update environment for this stage
                ck_info["pipeline"]["stages"][stage_name]["environment"] = (
                    environment_name
                )
                # Write back to calkit.yaml
                with open("calkit.yaml", "w") as f:
                    calkit.ryaml.dump(ck_info, f)
                self.log.info(
                    f"Set environment '{environment_name}' for notebook"
                    f" '{notebook_path}' in pipeline stage '{stage_name}'"
                    " successfully"
                )
                self.finish(json.dumps({"ok": True}))
                return
        # Update or add notebook entry
        notebooks = ck_info.get("notebooks", [])
        for nb in notebooks:
            if nb.get("path") == notebook_path:
                nb["environment"] = environment_name
                break
        else:
            notebooks.append(
                {"path": notebook_path, "environment": environment_name}
            )
        ck_info["notebooks"] = notebooks
        # Write back to calkit.yaml
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        self.log.info(
            f"Set environment '{environment_name}' for notebook"
            f" '{notebook_path}' successfully"
        )
        self.finish(json.dumps({"ok": True}))


class NotebookKernelRouteHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        """Get the kernel info for a notebook's environment."""
        body = self.get_json_body()
        if not body:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must be valid JSON"})
            )
            return
        notebook_path = body.get("path", "")
        env_name = body.get("environment", "")
        self.log.info(
            f"NotebookKernelRouteHandler.post() called with path:"
            f" '{notebook_path}', environment: '{env_name}'"
        )
        if not notebook_path or not env_name:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {"error": "Both 'path' and 'environment' are required"}
                )
            )
            return
        try:
            kernel_name = check_env_kernel(env_name=env_name)
        except Exception as e:
            self.log.error(f"Failed to check env kernel for {env_name}: {e}")
            self.set_status(500)
            self.finish(
                json.dumps(
                    {"error": f"Failed to check environment kernel: {e}"}
                )
            )
            return
        self.finish(json.dumps({"name": kernel_name}))


class NotebookStageRouteHandler(APIHandler):
    @tornado.web.authenticated
    def put(self):
        """Set the pipeline stage for a notebook."""
        body = self.get_json_body()
        if not body:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must be valid JSON"})
            )
            return
        notebook_path = body.get("path")
        stage_name = body.get("stage_name")
        env_name = body.get("environment")
        inputs = body.get("inputs", [])
        outputs = body.get("outputs", [])
        if not notebook_path or not stage_name or not env_name:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            "Request body must include 'path' and 'stage_name'"
                        )
                    }
                )
            )
            return
        ck_info = calkit.load_calkit_info()
        stages = ck_info.get("pipeline", {}).get("stages", {})
        if (
            stage_name in stages
            and stages[stage_name].get("notebook_path") != notebook_path
        ):
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            f"Stage '{stage_name}' already exists for a"
                            " different notebook"
                        )
                    }
                )
            )
            return
        # TODO: If this notebook is already part of a stage, handle renaming
        # Update or add the stage
        stage = stages.get(stage_name, {})
        stage["kind"] = "jupyter-notebook"
        stage["notebook_path"] = notebook_path
        stage["environment"] = env_name
        if "inputs" in body:
            stage["inputs"] = inputs
        if "outputs" in body:
            stage["outputs"] = outputs
        if "pipeline" not in ck_info:
            ck_info["pipeline"] = {}
        stages[stage_name] = stage
        ck_info["pipeline"]["stages"] = stages
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        self.log.info(
            f"Set stage '{stage_name}' for notebook '{notebook_path}' with "
            f"environment '{env_name}', inputs: {inputs}, outputs: {outputs}"
        )
        self.finish(json.dumps({"ok": True}))


class NotebookStageRunSessionRouteHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        """Create a notebook stage run session.

        This endpoint exists such that when a notebook is run top-to-bottom
        with a fresh kernel in the JupyterLab interface, we can cache it with
        DVC to avoid having to run it again.

        The back end will not keep track of state, so the front end must send
        all of it back in the PUT request.

        What goes in the lock file looks something like:

        stages:
          sup1-notebook:
            cmd: calkit nb execute --environment main --no-check
              --language python --to html "sup1.ipynb"
            deps:
            - path: .calkit/env-locks/main
            hash: md5
            md5: ca2ffab71e00d528b974e583d789ec97.dir
            size: 1226
            nfiles: 1
            - path: .calkit/notebooks/cleaned/sup1.ipynb
            hash: md5
            md5: 1ea6e3cb971fa3f18a01f1d017e08b01
            size: 753
            - path: README.md
            hash: md5
            md5: ae7619a99c0b70a537a73f1cccb91f14
            size: 26
            outs:
            - path: .calkit/notebooks/executed/sup1.ipynb
            hash: md5
            md5: 7b8186b295fbc66b85c504c7184591e5
            size: 22306
            - path: .calkit/notebooks/html/sup1.html
            hash: md5
            md5: 32795b3bb750c2e9fe162657c67d4fde
            size: 291084
        """
        body = self.get_json_body()
        if not body:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must be valid JSON"})
            )
            return
        notebook_path = body.get("notebook_path")
        stage_name = body.get("stage_name")
        if not notebook_path or not stage_name:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            "Request body must include 'notebook_path' and "
                            "'stage_name'"
                        )
                    }
                )
            )
            return
        ck_info = calkit.load_calkit_info()
        stages = ck_info.get("pipeline", {}).get("stages", {})
        if stage_name not in stages:
            self.set_status(400)
            self.finish(
                json.dumps({"error": f"Stage '{stage_name}' does not exist"})
            )
            return
        stage_info = stages[stage_name]
        try:
            stage = JupyterNotebookStage.model_validate(stage_info)
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps(
                    {"error": f"Failed to validate stage '{stage_name}': {e}"}
                )
            )
            return
        if not stage.notebook_path == notebook_path:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            f"Stage '{stage_name}' is not for notebook "
                            f"'{notebook_path}'"
                        )
                    }
                )
            )
            return
        # Ensure DVC pipeline is compiled
        try:
            calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps({"error": f"Failed to compile DVC pipeline: {e}"})
            )
            return
        # Ensure all cleaned notebooks are up-to-date
        try:
            calkit.notebooks.clean_all_in_pipeline(ck_info=ck_info)
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps(
                    {"error": f"Failed to clean notebooks in pipeline: {e}"}
                )
            )
            return
        # Check the notebook environment
        try:
            calkit.cli.main.check_environment(env_name=stage.environment)
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps({"error": f"Environment check failed: {e}"})
            )
            return
        # Read the DVC stage so we can save that and hashes of its deps/outs
        with open("dvc.yaml", "r") as f:
            dvc_yaml = calkit.ryaml.load(f)
        dvc_stages = dvc_yaml.get("stages", {})
        if stage_name not in dvc_stages:
            self.set_status(500)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            f"DVC stage '{stage_name}' not found in dvc.yaml"
                        )
                    }
                )
            )
            return
        dvc_stage = dvc_stages[stage_name]
        session = {
            "notebook_path": notebook_path,
            "stage_name": stage_name,
            "dvc_stage": dvc_stage,
        }
        # Hash all deps and outs
        dep_paths = dvc_stage.get("deps", [])
        out_paths = calkit.dvc.out_paths_from_stage(dvc_stage)
        lock_deps = [calkit.dvc.hash_path(dep) for dep in dep_paths]
        lock_outs = [
            calkit.dvc.hash_path(out)
            for out in out_paths
            if os.path.exists(out)
        ]
        session["lock_deps"] = lock_deps
        session["lock_outs"] = lock_outs
        self.finish(json.dumps(session))

    @tornado.web.authenticated
    def put(self):
        """Update a notebook stage run session, which essentially means it
        should be done.

        If the DVC stage command or any of the dep hashes have changed, it
        means we need to rerun the notebook, i.e., the run session can't be
        used to update the DVC lock file.
        """
        body = self.get_json_body()
        if not body:
            self.set_status(400)
            self.finish(
                json.dumps({"error": "Request body must be valid JSON"})
            )
            return
        required_keys = [
            "notebook_path",
            "stage_name",
            "dvc_stage",
            "lock_deps",
        ]
        for key in required_keys:
            if key not in body:
                self.set_status(400)
                self.finish(
                    json.dumps({"error": f"Request body must include '{key}'"})
                )
                return
        notebook_path = body["notebook_path"]
        stage_name = body["stage_name"]
        session_dvc_stage = body["dvc_stage"]
        session_lock_deps = body["lock_deps"]
        ck_info = calkit.load_calkit_info()
        stages = ck_info.get("pipeline", {}).get("stages", {})
        if stage_name not in stages:
            self.set_status(400)
            self.finish(
                json.dumps({"error": f"Stage '{stage_name}' does not exist"})
            )
            return
        stage_info = stages[stage_name]
        try:
            stage = JupyterNotebookStage.model_validate(stage_info)
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps(
                    {"error": f"Failed to validate stage '{stage_name}': {e}"}
                )
            )
            return
        if not stage.notebook_path == notebook_path:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            f"Stage '{stage_name}' is not for notebook "
                            f"'{notebook_path}'"
                        )
                    }
                )
            )
            return
        # Compile DVC pipeline again to be sure
        try:
            calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps({"error": f"Failed to compile DVC pipeline: {e}"})
            )
            return
        # Clean pipeline notebooks again to check hashes
        try:
            calkit.notebooks.clean_all_in_pipeline(ck_info=ck_info)
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps(
                    {"error": f"Failed to clean notebooks in pipeline: {e}"}
                )
            )
            return
        # Check the notebook environment again
        try:
            calkit.cli.main.check_environment(env_name=stage.environment)
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps({"error": f"Environment check failed: {e}"})
            )
            return
        # Read the DVC stage so we can compare that and hashes of its deps
        with open("dvc.yaml", "r") as f:
            dvc_yaml = calkit.ryaml.load(f)
        dvc_stages = dvc_yaml.get("stages", {})
        if stage_name not in dvc_stages:
            self.set_status(500)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            f"DVC stage '{stage_name}' not found in dvc.yaml"
                        )
                    }
                )
            )
            return
        dvc_stage = dvc_stages[stage_name]
        # Compare stage commands
        if dvc_stage.get("cmd") != session_dvc_stage.get("cmd"):
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            "DVC stage command has changed since session"
                            " creation"
                        )
                    }
                )
            )
            return
        # Compare dep hashes
        current_lock_deps = []
        dep_paths = dvc_stage.get("deps", [])
        for dep in dep_paths:
            dep_hash = calkit.dvc.hash_path(dep)
            current_lock_deps.append(dep_hash)
        if current_lock_deps != session_lock_deps:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            "DVC stage dependencies have changed since"
                            " session creation"
                        )
                    }
                )
            )
            return
        # Check that the notebook has been executed top-to-bottom with no
        # repeated cell executions
        try:
            with open(notebook_path, "r", encoding="utf-8") as f:
                nb_content = json.load(f)
            count = 0
            for cell in nb_content.get("cells", []):
                if cell.get("cell_type") != "code":
                    continue
                # If the cell is all whitespace, it won't ever be run, so we
                # can skip it
                if "".join(cell.get("source", [])).strip() == "":
                    continue
                if (
                    "execution_count" not in cell
                    or cell["execution_count"] is None
                ):
                    raise ValueError("Notebook has unexecuted cells")
                count += 1
                if cell["execution_count"] != count:
                    raise ValueError(
                        "Notebook cells were not executed in order"
                    )
        except Exception as e:
            self.set_status(400)
            self.finish(
                json.dumps(
                    {
                        "error": (
                            f"Notebook '{notebook_path}' was not executed"
                            f" top-to-bottom without repeated cells: {e}"
                        )
                    }
                )
            )
            return
        # If we've made it this far, we are okay to copy the notebook into the
        # executed notebooks folder, convert to HTML, and update the DVC lock
        # file
        executed_ipynb_path = calkit.notebooks.get_executed_notebook_path(
            notebook_path=notebook_path, to="notebook"
        )
        html_path = calkit.notebooks.get_executed_notebook_path(
            notebook_path=notebook_path, to="html"
        )
        os.makedirs(os.path.dirname(executed_ipynb_path), exist_ok=True)
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        # Copy executed notebook
        shutil.copy(notebook_path, executed_ipynb_path)
        # Convert to HTML
        folder = os.path.dirname(html_path)
        os.makedirs(folder, exist_ok=True)
        fname_out = os.path.basename(html_path)
        # Now convert without executing or checking the environment
        cmd = [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            executed_ipynb_path,
            "--to",
            "html",
            "--output-dir",
            Path(folder).as_posix(),
            "--output",
            fname_out,
        ]
        self.log.info(f"Exporting html via: {' '.join(cmd)}")
        p = subprocess.run(cmd)
        if p.returncode != 0:
            self.set_status(500)
            self.finish(
                json.dumps({"error": "Failed to convert notebook to HTML"})
            )
            return
        # Write to dvc.lock
        dep_paths = dvc_stage.get("deps", [])
        out_paths = calkit.dvc.out_paths_from_stage(dvc_stage)
        lock_deps = [calkit.dvc.hash_path(dep) for dep in dep_paths]
        lock_outs = [calkit.dvc.hash_path(out) for out in out_paths]
        dvc_lock_entry = {
            "cmd": dvc_stage.get("cmd"),
            "deps": lock_deps,
            "outs": lock_outs,
        }
        if not os.path.isfile("dvc.lock"):
            dvc_lock = {"schema": "2.0", "stages": {}}
        else:
            with open("dvc.lock", "r") as f:
                dvc_lock = calkit.ryaml.load(f)
        if "stages" not in dvc_lock:
            dvc_lock["stages"] = {}
        dvc_lock["stages"][stage_name] = dvc_lock_entry
        with open("dvc.lock", "w") as f:
            calkit.ryaml.dump(dvc_lock, f)
        self.log.info(
            f"Updated DVC lock file for stage '{stage_name}' successfully"
        )
        # Now, lastly, we need to populate the DVC cache for any cached outputs
        # so that the user doesn't have to rerun the notebook again
        # Check which outputs are cacheable (don't have cache: false)
        for out in dvc_stage.get("outs", []):
            if isinstance(out, str):
                out_path = out
                is_cached = True
            elif isinstance(out, dict):
                out_path = list(out.keys())[0]
                out_config = out[out_path]
                is_cached = out_config.get("cache", True)
            else:
                continue
            if is_cached and os.path.exists(out_path):
                self.log.info(f"Committing output to DVC cache: {out_path}")
                p = subprocess.run(
                    [sys.executable, "-m", "dvc", "commit", out_path],
                    capture_output=True,
                    text=True,
                )
                if p.returncode != 0:
                    self.log.warning(
                        f"Failed to commit {out_path} to DVC cache: "
                        f"{p.stderr.strip()}"
                    )
                else:
                    self.log.info(
                        f"Successfully committed {out_path} to DVC cache"
                    )
        self.finish(json.dumps({"ok": True, "dvc_lock_entry": dvc_lock_entry}))


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
            # First make sure pipeline is compiled
            ck_info = calkit.load_calkit_info()
            calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
            # Clean all notebooks in the pipeline
            calkit.notebooks.clean_all_in_pipeline(ck_info=ck_info)
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
                        "stale_stages": pipeline_status,
                        "is_outdated": is_outdated,
                    }
                )
            )
        except NotDvcRepoError:
            self.finish(json.dumps({"stale_stages": {}, "is_outdated": False}))
            return
        except Exception as e:
            self.set_status(500)
            self.finish(
                json.dumps(
                    {
                        "stale_stagess": {},
                        "is_outdated": False,
                        "error": f"Failed to get pipeline status: {e}",
                    }
                )
            )
            return


class PipelineRunsRouteHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        body = self.get_json_body() or {}
        targets = body.get("targets")
        try:
            res = calkit.cli.main.run(targets=targets)
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": f"Failed to run pipeline: {e}"}))
            return
        self.finish(json.dumps(res))


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
        name = self.get_argument("name", "")
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
                ] or (name and env_name != name):
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
        self.finish(json.dumps(envs))

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
        # Start kwargs for environment creation
        kwargs = dict(
            name=env_name, path=env_path, packages=packages, no_commit=True
        )
        # uv-venv, venv, and conda envs can have a prefix defined
        if env_kind in ["uv-venv", "venv", "conda"]:
            kwargs["prefix"] = body.get("prefix")
        # Use the Calkit CLI to create the environment
        func_to_kind = {
            "uv-venv": new_uv_venv,
            "venv": new_venv,
            "pixi": new_pixi_env,
            "julia": new_julia_env,
            "conda": new_conda_env,
        }
        try:
            func_to_kind[env_kind](**kwargs)
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


class SystemRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        """Get system information."""
        info = calkit.get_system_info()
        self.finish(json.dumps(info))


class SetupRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        """Get system setup info.

        This includes project and system requirements.

        ## System-level requirements

        1. Git installed.
        2. Git user.name set.
        3. Git user.email set.
        4. Calkit token set.

        ## Project-level

        1. Git remote set.
        2. DVC remote set.
        3. Git auth set.
        4. Calkit/DVC auth set.
        5. System-level project dependencies.
        6. Environmental variables.

        Indicate if these can be addressed programmatically or if they must
        be done with a URL.

        Response looks like a list of:

            kind: app | env-var | config
            name: str
            okay: bool
            value: str | float | int | bool | None
            programmatic: bool
            url: str | None
            instructions: str | None
        """
        pass

    @tornado.web.authenticated
    def post(self):
        """Take action to address a setup requirement.

        Body looks like:

            requirement:
              kind: app | env-var | config
              name: str
            value: str | None
        """
        pass


def setup_route_handlers(web_app):
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]
    # Automatically generate handlers from all APIHandler subclasses
    route_handler_classes = [
        cls
        for cls in globals().values()
        if isinstance(cls, type) and issubclass(cls, APIHandler)
    ]
    # Create names by splitting on capital letters
    handlers = []
    for cls in route_handler_classes:
        name = cls.__name__.removesuffix("RouteHandler")
        parts = []
        current_part = ""
        for char in name:
            if char.isupper() and current_part:
                parts.append(current_part.lower())
                current_part = char
            else:
                current_part += char
        if current_part:
            parts.append(current_part.lower())
        handlers.append((url_path_join(base_url, "calkit", *parts), cls))
    web_app.add_handlers(host_pattern, handlers)
