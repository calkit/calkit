"""Logic for checking project dependencies declared in ``calkit.yaml``.

The ``app``, ``env-var``, and ``calkit-config`` kinds are handled directly
by :func:`calkit.core.check_dep_exists`. This module adds support for the
``setup`` kind, which represents a per-machine precondition that isn't a
file -- the canonical example is ``gh auth login``, which must be done
once per clone and can be probed with ``gh auth status``.

A ``setup`` dep declares:

- ``check_command``: a shell command; exit 0 = satisfied.
- ``setup_command``: optional. Printed as a fix-it command for non-TTY
  runs (CI); on an interactive TTY the user is asked before we exec it.
- ``cache_ttl``: optional. Successful checks are cached in
  ``.calkit/local/dep-checks.sqlite`` for this long (default
  :data:`DEFAULT_SETUP_CACHE_TTL`) so repeated ``calkit run`` invocations
  don't re-probe network-bound commands. Cache entries also invalidate
  whenever the ``check_command`` itself changes, so editing
  ``calkit.yaml`` never silently relies on a stale result. Set
  ``cache_ttl: 0`` to disable caching for a specific dep.

To run a command inside a project environment, the user prefixes it with
``calkit xenv -n <env> --`` explicitly -- there's no implicit wrap,
because explicit is easier to reason about when commands fail.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import time
from typing import Any

# Path constants are duplicated from ``calkit/dvc/zip.py`` rather than
# imported to avoid pulling the DVC stack in for a simple dep check.
LOCAL_DIR = ".calkit/local"
DEP_CHECK_CACHE_PATH = LOCAL_DIR + "/dep-checks.sqlite"
# How long to cache a successful setup-dep check by default. One day is
# short enough that expiring credentials surface within a workday, and
# long enough that repeated ``calkit run`` invocations during active
# development don't re-probe network checks every time. Override per dep
# with ``cache_ttl``, or disable for one dep with ``cache_ttl: 0``.
DEFAULT_SETUP_CACHE_TTL = 24 * 60 * 60
_TTL_UNITS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
}
_TTL_RE = re.compile(r"^\s*(\d+)\s*([smhdw]?)\s*$", re.IGNORECASE)


def _format_uvx_from(spec: str) -> str:
    """Format a calkit version spec into a ``uvx --from`` argument.

    A bare version like ``0.38`` becomes ``calkit-python@0.38`` (uv's
    exact-pin shorthand); a PEP 440 specifier like ``>=0.38`` is
    appended directly, e.g. ``calkit-python>=0.38``.
    """
    spec = spec.strip()
    if not spec:
        return "calkit-python"
    if spec[0].isdigit():
        return f"calkit-python@{spec}"
    return f"calkit-python{spec}"


def _suggest_version_from_spec(spec: str) -> str | None:
    """Pull the first version-looking token out of ``spec`` for a hint."""
    m = re.search(r"\d[\w.+\-!]*", spec)
    return m.group(0) if m else None


def check_calkit_version(spec: str) -> None:
    """Verify the running calkit satisfies ``spec`` (e.g. ``>=0.38``).

    Raises ``ValueError`` with a fix-it message pointing the user at
    ``calkit --use-version`` or ``calkit upgrade`` when the installed
    version is outside the requested specifier. A bare version like
    ``0.38`` is interpreted as ``==0.38`` so users can write
    ``- calkit==0.38`` or simply ``- calkit>=0.38`` in ``calkit.yaml``.
    """
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version

    import calkit

    raw = (spec or "").strip()
    if not raw:
        return
    spec_str = raw if raw[0] in "<>=!~" else f"=={raw}"
    try:
        spec_set = SpecifierSet(spec_str)
    except Exception as e:
        raise ValueError(f"Invalid calkit version spec '{spec}': {e}")
    try:
        current = Version(calkit.__version__)
    except InvalidVersion:
        # A dev/editable install with an unparseable version: don't block.
        return
    if current in spec_set:
        return
    suggested = _suggest_version_from_spec(spec_str)
    msg = (
        f"calkit{spec_str} required, but installed version is "
        f"{calkit.__version__}."
    )
    if suggested:
        msg += (
            f" Re-run with 'calkit --use-version {suggested} ...' or "
            "upgrade with 'calkit upgrade'."
        )
    else:
        msg += " Upgrade with 'calkit upgrade'."
    raise ValueError(msg)


def parse_ttl(ttl: str | int | float) -> int:
    """Parse a TTL like ``30s``, ``5m``, ``2h``, ``7d``, ``1w`` into seconds.

    Bare numbers are seconds. ``0`` disables caching (caller's contract).
    Raises ``ValueError`` on garbage so misconfiguration surfaces at
    check time rather than silently disabling the cache.
    """
    if isinstance(ttl, (int, float)):
        return int(ttl)
    m = _TTL_RE.match(str(ttl))
    if m is None:
        raise ValueError(
            f"Invalid cache_ttl '{ttl}'; expected forms like '30s', '5m', "
            "'2h', '7d', '1w', or a bare integer number of seconds"
        )
    n, unit = m.groups()
    return int(n) * _TTL_UNITS.get(unit.lower(), 1)


def _hash_check_cmd(check: str | None) -> str:
    """Hash the check command so cache entries invalidate when it changes."""
    return hashlib.sha256((check or "").encode("utf-8")).hexdigest()


def _ensure_local_dir(wdir: str | None) -> str:
    base = os.path.join(wdir, LOCAL_DIR) if wdir else LOCAL_DIR
    os.makedirs(base, exist_ok=True)
    gitignore = os.path.join(base, ".gitignore")
    if not os.path.isfile(gitignore):
        with open(gitignore, "w") as f:
            f.write("*\n")
    return base


def _cache_path(wdir: str | None) -> str:
    return (
        os.path.join(wdir, DEP_CHECK_CACHE_PATH)
        if wdir
        else DEP_CHECK_CACHE_PATH
    )


def _cache_open(wdir: str | None):
    """Open the SqliteDict cache, creating the local dir on demand."""
    from sqlitedict import SqliteDict

    _ensure_local_dir(wdir)
    return SqliteDict(_cache_path(wdir), autocommit=True)


def cache_lookup(
    name: str,
    check: str | None,
    *,
    wdir: str | None = None,
) -> dict | None:
    """Return a fresh cache entry for ``name``, or None if missing/expired.

    Entries also invalidate when the ``check`` command hash changes, so
    editing ``calkit.yaml`` never silently relies on a stale result.
    """
    if not os.path.isfile(_cache_path(wdir)):
        return None
    with _cache_open(wdir) as cache:
        entry = cache.get(name)
        if not entry:
            return None
        ttl_s = entry.get("ttl_seconds", 0)
        passed_at = entry.get("passed_at", 0)
        if ttl_s > 0 and (time.time() - passed_at) > ttl_s:
            return None
        if entry.get("check_hash") != _hash_check_cmd(check):
            return None
        return entry


def cache_record(
    name: str,
    check: str | None,
    ttl_seconds: int,
    *,
    wdir: str | None = None,
) -> None:
    with _cache_open(wdir) as cache:
        cache[name] = {
            "passed_at": time.time(),
            "ttl_seconds": int(ttl_seconds),
            "check_hash": _hash_check_cmd(check),
        }


def cache_clear(*, wdir: str | None = None) -> None:
    """Remove all cached dependency-check entries (used by ``--no-cache``)."""
    if not os.path.isfile(_cache_path(wdir)):
        return
    with _cache_open(wdir) as cache:
        cache.clear()


def _run_shell(
    cmd: str, *, capture: bool = True
) -> subprocess.CompletedProcess:
    """Run ``cmd`` through the user's shell; mirrors how they would run it."""
    return subprocess.run(cmd, shell=True, capture_output=capture, text=True)


def _is_interactive() -> bool:
    """True only when both stdin and stdout are TTYs.

    Stdout matters because the prompt needs to render; stdin matters because
    we need to read the user's answer. CI environments fail at least one
    and fall through to the abort-with-fix-command path.
    """
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _resolve_cache_ttl(dep: dict[str, Any]) -> int:
    """Resolve the effective cache TTL for a setup dep.

    Defaults to ``DEFAULT_SETUP_CACHE_TTL`` when ``cache_ttl`` is absent;
    ``cache_ttl: 0`` explicitly disables caching.
    """
    raw = dep.get("cache_ttl")
    if raw is None:
        return DEFAULT_SETUP_CACHE_TTL
    return parse_ttl(raw)


def check_setup_dep(
    dep: dict[str, Any],
    *,
    interactive: bool | None = None,
    use_cache: bool = True,
    wdir: str | None = None,
) -> bool:
    """Check a ``kind: setup`` dependency.

    Returns True if satisfied (or successfully made satisfied via the
    setup command), False otherwise. Successful checks are cached for
    ``cache_ttl`` (defaulting to one day) under ``.calkit/local`` so
    repeated runs skip re-probing. The caller can pass ``use_cache=False``
    to bypass and force re-probing, which the CLI exposes as ``--no-cache``.
    """
    name = dep.get("name")
    if not name:
        raise ValueError(f"setup dependency missing 'name': {dep}")
    check_command = dep.get("check_command")
    setup_command = dep.get("setup_command")
    if not check_command:
        raise ValueError(
            f"setup dependency '{name}' must declare 'check_command'"
        )
    if interactive is None:
        interactive = _is_interactive()
    ttl_seconds = _resolve_cache_ttl(dep)
    # Cache hit short-circuits the probe entirely.
    if use_cache and ttl_seconds > 0:
        hit = cache_lookup(name, check_command, wdir=wdir)
        if hit is not None:
            return True
    result = _run_shell(check_command)
    if result.returncode == 0:
        if ttl_seconds > 0:
            cache_record(name, check_command, ttl_seconds, wdir=wdir)
        return True
    return _try_setup(
        name=name,
        check_command=check_command,
        setup_command=setup_command,
        interactive=interactive,
        ttl_seconds=ttl_seconds,
        wdir=wdir,
        failure_reason=(result.stderr or result.stdout or "").strip(),
    )


def prompt_and_store_env_var(
    name: str,
    *,
    default: str | None = None,
    dotenv_path: str = ".env",
) -> str | None:
    """Prompt the user for an env-var value, persist it to ``.env``, set it
    on ``os.environ``, and return the value.

    Returns ``None`` if the user aborted (EOF / no value and no default).
    The caller decides whether that is fatal. ``.env`` is appended to
    ``.gitignore`` if not already ignored, mirroring ``calkit check
    env-vars`` so secrets don't sneak into git.
    """
    import dotenv

    prompt = f"Enter a value for {name}"
    if default is not None:
        prompt += f" [{default}]"
    try:
        raw = input(prompt + ": ")
    except EOFError:
        return None
    value = raw.strip() or default
    if value is None:
        return None
    dotenv.set_key(
        dotenv_path=dotenv_path, key_to_set=name, value_to_set=value
    )
    os.environ[name] = value
    _ensure_env_gitignored(dotenv_path)
    return value


def _ensure_env_gitignored(dotenv_path: str) -> None:
    """Append ``dotenv_path`` to ``.gitignore`` if not already ignored.

    Falls back to a plain ``.gitignore`` append when the project isn't a
    git repo so this helper is safe to call from non-git contexts.
    """
    try:
        import calkit.git

        repo = calkit.git.get_repo()
        if repo.ignored(dotenv_path):
            return
    except Exception:
        pass
    try:
        with open(".gitignore", "a") as f:
            f.write(f"\n{dotenv_path}\n")
    except OSError:
        pass


def _try_setup(
    *,
    name: str,
    check_command: str,
    setup_command: str | None,
    interactive: bool,
    ttl_seconds: int,
    wdir: str | None,
    failure_reason: str,
) -> bool:
    """Common failure path: prompt-and-run on TTY, else print and abort.

    After setup runs we re-verify ``check_command`` so a setup that
    *claims* success but doesn't actually satisfy the dep is caught here
    instead of failing later inside the pipeline. A successful
    re-verification populates the cache so we don't immediately re-probe
    on the next ``calkit run``.
    """
    print(f"Setup dependency '{name}' is not satisfied.")
    if failure_reason:
        print(f"  Reason: {failure_reason}")
    if not setup_command:
        print(
            f"  No 'setup_command' declared; satisfy '{name}' manually and "
            "re-run."
        )
        return False
    if not interactive:
        print(f"  To satisfy, run:  {setup_command}")
        return False
    try:
        answer = (
            input(f"Run setup now ({setup_command!r})? [Y/n] ").strip().lower()
        )
    except EOFError:
        answer = "n"
    if answer not in ("", "y", "yes"):
        print(f"  Skipped. To satisfy, run:  {setup_command}")
        return False
    # capture=False so interactive setup tools (e.g., the browser-based
    # ``gh auth login`` flow) can talk to the terminal directly.
    result = _run_shell(setup_command, capture=False)
    if result.returncode != 0:
        print(f"  Setup command exited {result.returncode}.")
        return False
    verify = _run_shell(check_command)
    if verify.returncode != 0:
        print(
            "  Setup ran but check still fails; satisfy manually and re-run."
        )
        return False
    if ttl_seconds > 0:
        cache_record(name, check_command, ttl_seconds, wdir=wdir)
    return True
