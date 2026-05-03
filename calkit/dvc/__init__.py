from .core import *  # noqa: F403


def __getattr__(name: str):
    import importlib

    try:
        mod = importlib.import_module(f"calkit.dvc.{name}")
        globals()[name] = mod
        return mod
    except ModuleNotFoundError:
        raise AttributeError(f"module 'calkit.dvc' has no attribute {name!r}")
