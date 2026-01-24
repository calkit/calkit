__version__ = "0.33.3"

from .core import *  # noqa: F403, I001
from . import git  # noqa: F401
from . import dvc  # noqa: F401
from . import cloud  # noqa: F401
from . import jupyter  # noqa: F401
from . import config  # noqa: F401
from . import models  # noqa: F401
from . import office  # noqa: F401
from . import templates  # noqa: F401
from . import conda  # noqa: F401
from . import calc  # noqa: F401
from . import check  # noqa: F401
from . import github  # noqa: F401
from . import invenio  # noqa: F401
from . import releases  # noqa: F401
from . import licenses  # noqa: F401
from . import overleaf  # noqa: F401
from .notebooks import declare_notebook  # noqa: F401
from .jupyterlab.routes import setup_route_handlers


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

    # Change to root_dir so all handlers work in the correct directory context
    root_dir = server_app.root_dir
    os.chdir(root_dir)
    server_app.log.info(f"Changed working directory to {root_dir}")
    setup_route_handlers(server_app.web_app)
    name = "calkit"
    server_app.log.info(f"Registered {name} server extension")
