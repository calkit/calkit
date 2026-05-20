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

    # Only scan the group's option region -- the tokens before the first
    # subcommand (or the ``--`` end-of-options marker). A ``--use-version``
    # buried in a forwarded arg (e.g. ``calkit xenv -- some-tool
    # --use-version 1.0``) must not trigger a re-exec.
    argv = sys.argv[1:]
    version_spec: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            break
        if not a.startswith("-"):
            # First non-option token is the subcommand name; stop here.
            break
        if a == "--use-version" and i + 1 < len(argv):
            version_spec = argv[i + 1]
            break
        if a.startswith("--use-version="):
            version_spec = a.split("=", 1)[1]
            break
        # Skip past an option's value when it takes one (heuristic: a
        # following token that doesn't itself look like a flag). Worst
        # case we treat a flag-with-no-value as one with one, which only
        # affects where the loop terminates -- the outer ``break``s above
        # still fire first if --use-version is present.
        if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            i += 2
        else:
            i += 1
    if not version_spec:
        return
    from .main.core import _exec_with_version

    _exec_with_version(version_spec)
