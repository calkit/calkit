"""Open an interactive shell with an environment activated.

An environment is activated by putting its programs first on PATH, setting
the variables its kind sets, e.g., ``VIRTUAL_ENV`` or ``CONDA_PREFIX``, and
running its activation scripts. That's done after the shell has read its own
startup files, since those often change PATH, e.g., to activate Conda's base
environment, which would otherwise come first.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field

# Kinds a shell can be opened in, which are the ones kept on this machine as
# a folder of programs
SHELL_KINDS = ("conda", "uv", "uv-venv", "venv", "pixi")


@dataclass
class Activation:
    """What activating an environment changes in a shell."""

    name: str
    # Put first on PATH, in this order
    path: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    unset: list[str] = field(default_factory=list)
    # Folders of activation scripts, e.g., Conda's activate.d, of which
    # those for the shell are run in name order
    script_dirs: list[str] = field(default_factory=list)


def get_unsupported_message(env_name: str, kind: str | None) -> str:
    """Why a shell can't be opened in an environment, and what to do."""
    return (
        f"Can't open a shell in environment '{env_name}', of kind '{kind}'; "
        f"run a program in it with 'calkit xenv -n {env_name} -- <command>' "
        "instead"
    )


def get_activation(env_name: str, env: dict, envs: dict) -> Activation:
    """Work out what activating an environment in a shell changes.

    Raises ``ValueError`` for an environment a shell can't be opened in, or
    one that hasn't been created.
    """
    import calkit
    import calkit.conda
    from calkit.environments.core import get_default_venv_prefix

    def get_venv_activation(prefix: str) -> Activation:
        bin_dir = os.path.join(
            prefix, "Scripts" if sys.platform == "win32" else "bin"
        )
        return Activation(
            name=env_name,
            path=[bin_dir],
            env_vars={"VIRTUAL_ENV": prefix, "VIRTUAL_ENV_PROMPT": env_name},
            # As venv's own activate script does
            unset=["PYTHONHOME"],
        )

    kind = env.get("kind")
    if kind == "uv":
        project_dir = os.path.dirname(os.path.abspath(env["path"]))
        venv = os.environ.get("UV_PROJECT_ENVIRONMENT") or ".venv"
        return get_venv_activation(
            os.path.normpath(os.path.join(project_dir, venv))
        )
    if kind in ("uv-venv", "venv"):
        prefix = env.get("prefix") or get_default_venv_prefix(
            envs, env["path"], env_name
        )
        return get_venv_activation(os.path.abspath(prefix))
    if kind == "pixi":
        cmd = ["pixi", "shell-hook", "--json"]
        if os.path.dirname(env["path"]):
            cmd += ["--manifest-path", os.path.abspath(env["path"])]
        if pixi_env_name := env.get("name"):
            cmd += ["--environment", pixi_env_name]
        try:
            out = subprocess.check_output(cmd, text=True)
            env_vars = dict(json.loads(out)["environment_variables"])
        except (
            OSError,
            subprocess.CalledProcessError,
            ValueError,
            KeyError,
        ) as e:
            raise ValueError(f"Failed to get Pixi's activation: {e}")
        # Pixi gives the whole PATH, of which what's before this one's is
        # what activating it adds
        current = os.environ.get("PATH", "").split(os.pathsep)
        path = []
        for d in env_vars.pop("PATH", "").split(os.pathsep):
            if d in current:
                break
            path.append(d)
        return Activation(name=env_name, path=path, env_vars=env_vars)
    if kind != "conda":
        raise ValueError(get_unsupported_message(env_name, kind))
    with open(env["path"], encoding="utf-8") as f:
        spec = calkit.ryaml.load(f) or {}
    spec_prefix = env.get("prefix") or spec.get("prefix")
    if spec_prefix is not None:
        prefix = os.path.abspath(spec_prefix)
    else:
        conda_exe = calkit.conda.find_conda_exe()
        if conda_exe is None:
            raise ValueError("Cannot find Conda")
        prefix = calkit.conda.find_named_env_prefix(spec["name"], conda_exe)
    if prefix is None or not os.path.isdir(os.path.join(prefix, "conda-meta")):
        raise ValueError(f"Environment '{env_name}' hasn't been created")
    if sys.platform == "win32":
        bin_dirs = [
            prefix,
            os.path.join(prefix, "Library", "mingw-w64", "bin"),
            os.path.join(prefix, "Library", "usr", "bin"),
            os.path.join(prefix, "Library", "bin"),
            os.path.join(prefix, "Scripts"),
            os.path.join(prefix, "bin"),
        ]
    else:
        bin_dirs = [os.path.join(prefix, "bin")]
    env_vars = {
        "CONDA_PREFIX": prefix,
        # What 'conda activate' sets it to
        "CONDA_DEFAULT_ENV": prefix if spec_prefix else str(spec["name"]),
        # Replacing the active one's, e.g., base's, in the prompt
        "CONDA_PROMPT_MODIFIER": f"({env_name}) ",
    }
    # Set with 'conda env config vars set'
    state_fpath = os.path.join(prefix, "conda-meta", "state")
    try:
        with open(state_fpath, encoding="utf-8") as f:
            state = json.load(f)
        env_vars |= {
            str(k): str(v) for k, v in state.get("env_vars", {}).items()
        }
    except (OSError, ValueError, AttributeError):
        pass
    return Activation(
        name=env_name,
        path=[d for d in bin_dirs if os.path.isdir(d)],
        env_vars=env_vars,
        # A venv that was active no longer runs
        unset=["VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT"],
        script_dirs=[os.path.join(prefix, "etc", "conda", "activate.d")],
    )


def get_default_shell() -> str:
    """The shell to open: the user's on POSIX, else PowerShell or cmd."""
    if sys.platform == "win32":
        for name in ("pwsh", "powershell"):
            if exe := shutil.which(name):
                return exe
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"


def get_shell_family(shell: str) -> str:
    """Which family of shells, by syntax, a shell's executable belongs to."""
    name = os.path.basename(shell).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name in ("bash", "zsh"):
        return name
    if name in ("sh", "dash", "ash", "ksh", "mksh", "yash"):
        return "sh"
    if name == "fish":
        return "fish"
    if name in ("pwsh", "powershell"):
        return "powershell"
    if name == "cmd":
        return "cmd"
    return "other"


def _quote_fish(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def get_activation_script(activation: Activation, family: str) -> str:
    """The commands that activate an environment in a family of shell,
    run after the shell's own startup files."""

    def get_scripts(ext: str) -> list[str]:
        found = []
        for d in activation.script_dirs:
            if os.path.isdir(d):
                found += [
                    os.path.join(d, f)
                    for f in sorted(os.listdir(d))
                    if f.endswith(ext)
                ]
        return found

    def quote_powershell(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def quote_cmd(value: str) -> str:
        return value.replace("%", "%%")

    name = activation.name
    lines = []
    q: Callable[[str], str]
    if family == "posix":
        q = shlex.quote
        if "CONDA_PROMPT_MODIFIER" in activation.env_vars:
            # Conda put the active environment's name first in the prompt
            lines.append('PS1="${PS1#"${CONDA_PROMPT_MODIFIER:-}"}"')
        if activation.path:
            lines.append(
                f'export PATH={q(os.pathsep.join(activation.path))}"'
                f'{os.pathsep}$PATH"'
            )
        lines += [f"export {k}={q(v)}" for k, v in activation.env_vars.items()]
        lines += [f"unset {k}" for k in activation.unset]
        lines += [f". {q(s)}" for s in get_scripts(".sh")]
        lines += [
            f"export CALKIT_SHELL={q(name)}",
            f'PS1={q(f"({name}) ")}"$PS1"',
        ]
    elif family == "fish":
        q = _quote_fish
        if activation.path:
            lines.append(
                "set -gx PATH "
                + " ".join(q(d) for d in activation.path)
                + " $PATH"
            )
        lines += [
            f"set -gx {k} {q(v)}" for k, v in activation.env_vars.items()
        ]
        lines += [f"set -e {k}" for k in activation.unset]
        lines += [f"source {q(s)}" for s in get_scripts(".fish")]
        lines += [
            f"set -gx CALKIT_SHELL {q(name)}",
            "functions -q fish_prompt; and functions -c fish_prompt "
            "_calkit_fish_prompt",
            f"function fish_prompt; echo -n {q(f'({name}) ')}; "
            "functions -q _calkit_fish_prompt; and _calkit_fish_prompt; end",
        ]
    elif family == "powershell":
        q = quote_powershell
        if activation.path:
            lines.append(
                f"$env:PATH = {q(os.pathsep.join(activation.path) + os.pathsep)}"
                " + $env:PATH"
            )
        lines += [f"$env:{k} = {q(v)}" for k, v in activation.env_vars.items()]
        lines += [
            f"Remove-Item Env:{k} -ErrorAction SilentlyContinue"
            for k in activation.unset
        ]
        lines += [f". {q(s)}" for s in get_scripts(".ps1")]
        lines += [
            f"$env:CALKIT_SHELL = {q(name)}",
            "$global:_CalkitPrompt = $function:prompt",
            "function global:prompt { "
            f"{q(f'({name}) ')} + (& $global:_CalkitPrompt) }}",
        ]
    elif family == "cmd":
        q = quote_cmd
        lines.append("@echo off")
        if activation.path:
            lines.append(
                f'set "PATH={q(os.pathsep.join(activation.path))};%PATH%"'
            )
        lines += [f'set "{k}={q(v)}"' for k, v in activation.env_vars.items()]
        lines += [f'set "{k}="' for k in activation.unset]
        lines += [f'call "{s}"' for s in get_scripts(".bat")]
        lines += [
            f'set "CALKIT_SHELL={q(name)}"',
            f"if defined PROMPT (prompt ({q(name)}) %PROMPT%) "
            f"else (prompt ({q(name)}) $P$G)",
        ]
    else:
        raise ValueError(f"No activation script for shells like '{family}'")
    return "\n".join(lines) + "\n"


def prepare(
    shell: str,
    activation: Activation,
    tmpdir: str,
    base_env: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """The command and process environment that open a shell with an
    environment activated, writing what it reads to ``tmpdir``.

    A shell this doesn't know gets the environment's variables to start with,
    which its startup files may undo.
    """

    def get_activated_env(base: dict[str, str]) -> dict[str, str]:
        """A process environment with an environment activated in it."""
        env = dict(base)
        if activation.path:
            env["PATH"] = os.pathsep.join(
                activation.path + [env.get("PATH", "")]
            )
        env |= activation.env_vars
        for k in activation.unset:
            env.pop(k, None)
        env["CALKIT_SHELL"] = activation.name
        return env

    family = get_shell_family(shell)
    env = dict(os.environ if base_env is None else base_env)
    if family == "other":
        return [shell], get_activated_env(env)
    script = get_activation_script(
        activation, "posix" if family in ("bash", "zsh", "sh") else family
    )
    q = shlex.quote
    if family in ("bash", "zsh", "sh"):
        tail = os.path.join(tmpdir, "activate.sh")
        with open(tail, "w", encoding="utf-8") as f:
            f.write(script)
    if family == "bash":
        rc = os.path.join(tmpdir, "bashrc")
        with open(rc, "w", encoding="utf-8") as f:
            f.write(
                f'[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"\n. {q(tail)}\n'
            )
        return [shell, "--rcfile", rc, "-i"], env
    if family == "zsh":
        # zsh reads its startup files from ZDOTDIR, so it's pointed here,
        # and these read the user's, from wherever they are
        if "ZDOTDIR" in env:
            env["CALKIT_USER_ZDOTDIR"] = env["ZDOTDIR"]
        env["ZDOTDIR"] = tmpdir
        with open(os.path.join(tmpdir, ".zshenv"), "w", encoding="utf-8") as f:
            f.write(
                '_calkit_zdotdir="$ZDOTDIR"\n'
                'if [[ -n "${CALKIT_USER_ZDOTDIR+x}" ]]; then\n'
                '  ZDOTDIR="$CALKIT_USER_ZDOTDIR"\n'
                "else\n"
                "  unset ZDOTDIR\n"
                "fi\n"
                "unset CALKIT_USER_ZDOTDIR\n"
                '[[ -f "${ZDOTDIR:-$HOME}/.zshenv" ]] && '
                '. "${ZDOTDIR:-$HOME}/.zshenv"\n'
                '[[ -n "${ZDOTDIR+x}" ]] && _calkit_user_zdotdir="$ZDOTDIR"\n'
                'ZDOTDIR="$_calkit_zdotdir"\n'
            )
        with open(os.path.join(tmpdir, ".zshrc"), "w", encoding="utf-8") as f:
            f.write(
                'if [[ -n "${_calkit_user_zdotdir+x}" ]]; then\n'
                '  ZDOTDIR="$_calkit_user_zdotdir"\n'
                "else\n"
                "  unset ZDOTDIR\n"
                "fi\n"
                "unset _calkit_user_zdotdir _calkit_zdotdir\n"
                '[[ -f "${ZDOTDIR:-$HOME}/.zshrc" ]] && '
                '. "${ZDOTDIR:-$HOME}/.zshrc"\n'
                f". {q(tail)}\n"
            )
        return [shell, "-i"], env
    if family == "sh":
        # An interactive POSIX shell reads the file ENV names
        rc = os.path.join(tmpdir, "shrc")
        user_env = env.get("ENV")
        with open(rc, "w", encoding="utf-8") as f:
            if user_env:
                f.write(f"[ -f {q(user_env)} ] && . {q(user_env)}\n")
            f.write(f". {q(tail)}\n")
        env["ENV"] = rc
        return [shell, "-i"], env
    if family == "fish":
        tail = os.path.join(tmpdir, "activate.fish")
        with open(tail, "w", encoding="utf-8") as f:
            f.write(script)
        # Run after fish's config files
        return [shell, "-C", f"source {_quote_fish(tail)}"], env
    if family == "powershell":
        # Passed as a command rather than a script file, which an execution
        # policy can forbid running
        encoded = base64.b64encode(script.encode("utf-16-le")).decode()
        return [shell, "-NoExit", "-EncodedCommand", encoded], env
    # cmd runs this after its AutoRun commands
    tail = os.path.join(tmpdir, "activate.bat")
    with open(tail, "w", encoding="utf-8") as f:
        f.write(script)
    return [shell, "/k", tail], env


def start(
    shell: str,
    activation: Activation,
    base_env: dict[str, str] | None = None,
    run: Callable[..., int] = subprocess.call,
) -> int:
    """Open a shell with an environment activated, returning its exit
    status once it's left."""
    with tempfile.TemporaryDirectory(prefix="calkit-shell-") as tmpdir:
        cmd, env = prepare(shell, activation, tmpdir, base_env=base_env)
        return run(cmd, env=env)
