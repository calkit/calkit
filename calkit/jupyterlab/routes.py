"""JupyterLab extension server routes."""

import glob
import json
import os

import tornado
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
from pydantic import BaseModel

import calkit


class HelloRouteHandler(APIHandler):
    # The following decorator should be present on all verb methods
    # (head, get, post, patch, put, delete, options) to ensure only authorized
    # users can request the Jupyter server
    @tornado.web.authenticated
    def get(self):
        self.finish(
            json.dumps(
                {
                    "data": (
                        "Hello, world!"
                        " This is the '/calkit/hello' endpoint."
                        " Try visiting me in your browser!"
                    ),
                }
            )
        )


class ProjectRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        self.log.info(f"Received request for project info in {os.getcwd()}")
        self.finish(json.dumps(calkit.load_calkit_info()))


class KernelspecsRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        self.log.info("Received request for calkit kernelspec info")
        specs = ["sup", "lol", "hehe"]
        self.finish(json.dumps({"kernelspecs": specs}))


class Notebook(BaseModel):
    path: str
    included_in_project: bool = False
    included_in_pipeline: bool = False
    stage_name: str | None = None


class NotebooksRouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self):
        """Get a list of notebooks in the project.

        We indicate if these are included in the notebooks section and if they
        are part of the pipeline.
        """
        self.log.info("Received request for calkit notebooks info")
        resp = []
        # Search for notebooks up to 3 directories deep, but not under .calkit
        # or .ipynb_checkpoints
        notebooks = glob.glob("**/*.ipynb", recursive=True)
        for nb in notebooks:
            if ".calkit/" in nb or ".ipynb_checkpoints/" in nb:
                continue
            resp.append(Notebook(path=nb))
        # Now check which notebooks are included in the project and pipeline
        ck_info = calkit.load_calkit_info()
        project_notebooks = ck_info.get("notebooks", [])
        for nb in resp:
            if nb.path in project_notebooks:
                nb.included_in_project = True
        stages = ck_info.get("pipeline", {}).get("stages", {})
        for stage_name, stage in stages.items():
            if stage.get("kind") == "jupyter-notebook":
                nb_path = stage.get("notebook_path")
                for nb in resp:
                    if nb.path == nb_path:
                        nb.included_in_pipeline = True
                        nb.stage_name = stage_name
        notebooks = [nb.model_dump() for nb in resp]
        self.finish(json.dumps({"notebooks": notebooks}))

    @tornado.web.authenticated
    def post(self):
        """Post a new notebook.

        If the file already exists, add it to the project notebooks and
        pipeline.
        """
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
    ]
    web_app.add_handlers(host_pattern, handlers)
