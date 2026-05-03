from importlib.metadata import version as _version

__version__ = _version("calkit-python")

from .core import *  # noqa: F403, I001

_SUBMODULES = {
    "git",
    "dvc",
    "cloud",
    "fs",
    "jupyter",
    "config",
    "models",
    "office",
    "templates",
    "conda",
    "calc",
    "check",
    "github",
    "invenio",
    "releases",
    "licenses",
    "overleaf",
    "julia",
    "notebooks",
    "environments",
    "pipeline",
    "matlab",
    "datasets",
    "detect",
    "docker",
    "gui",
    "magics",
    "ops",
    "server",
}


def __getattr__(name: str):
    if name in _SUBMODULES:
        import importlib

        mod = importlib.import_module(f"calkit.{name}")
        globals()[name] = mod
        return mod
    if name == "declare_notebook":
        from .notebooks import declare_notebook

        globals()["declare_notebook"] = declare_notebook
        return declare_notebook
    raise AttributeError(f"module 'calkit' has no attribute {name!r}")


def _jupyter_labextension_paths():
    return [{"src": "labextension", "dest": "calkit"}]


def _jupyter_server_extension_points():
    return [{"module": "calkit"}]


def _load_jupyter_server_extension(server_app):
    """Registers the API handler to receive HTTP requests from the frontend
    extension.

    Parameters
    ----------
    server_app: jupyterlab.labapp.LabApp
        JupyterLab application instance
    """
    import os

    from .jupyterlab.routes import (
        setup_route_handlers,  # deferred to avoid heavy tornado/jupyter_server import at CLI startup
    )

    # Change to root_dir so all handlers work in the correct directory context
    root_dir = server_app.root_dir
    os.chdir(root_dir)
    server_app.log.info(f"Changed working directory to {root_dir}")
    setup_route_handlers(server_app.web_app)
    name = "calkit"
    server_app.log.info(f"Registered {name} server extension")
