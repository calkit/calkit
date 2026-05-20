from .core import *  # noqa: F403


def run() -> None:
    # Intercept ``--use-version`` before Typer/Click parses argv: Click
    # processes eager options like ``--help`` and ``--version`` (and the
    # group's ``no_args_is_help``) ahead of the callback body, so an
    # invocation like ``calkit --use-version 0.1.1 -- --help`` would
    # otherwise print the *current* CLI's help instead of re-execing
    # under the requested version.
    _maybe_exec_with_version()
    from .main import app

    app()


def _maybe_exec_with_version() -> None:
    import sys

    argv = sys.argv[1:]
    version_spec: str | None = None
    for i, a in enumerate(argv):
        if a == "--use-version" and i + 1 < len(argv):
            version_spec = argv[i + 1]
            break
        if a.startswith("--use-version="):
            version_spec = a.split("=", 1)[1]
            break
    if not version_spec:
        return
    from .main.core import _exec_with_version

    _exec_with_version(version_spec)
