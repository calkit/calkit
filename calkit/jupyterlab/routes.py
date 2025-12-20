"""JupyterLab extension server routes."""

import json
import os

import tornado
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join

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


def setup_route_handlers(web_app):
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]
    hello_route_pattern = url_path_join(base_url, "calkit", "hello")
    project_route_pattern = url_path_join(base_url, "calkit", "project")
    handlers = [
        (hello_route_pattern, HelloRouteHandler),
        (project_route_pattern, ProjectRouteHandler),
    ]
    web_app.add_handlers(host_pattern, handlers)
