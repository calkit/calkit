from .core import *  # noqa: F403


def run() -> None:
    from .main import app

    app()
