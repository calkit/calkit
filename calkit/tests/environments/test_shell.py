"""Tests for ``calkit.environments.shell``."""

import base64
import json
import os
import shutil
import subprocess
import sys

import pytest

from calkit.environments import shell as env_shell


def _fake_conda_env(tmp_path, monkeypatch):
    """A Conda environment at a prefix, as far as activating it goes."""
    monkeypatch.chdir(tmp_path)
    prefix = tmp_path / ".conda-envs" / "main"
    bin_dir = prefix / ("Scripts" if sys.platform == "win32" else "bin")
    bin_dir.mkdir(parents=True)
    (prefix / "conda-meta").mkdir()
    (prefix / "conda-meta" / "state").write_text(
        json.dumps({"env_vars": {"MY_VAR": "from-conda"}})
    )
    activate_d = prefix / "etc" / "conda" / "activate.d"
    activate_d.mkdir(parents=True)
    (activate_d / "b.sh").write_text("export FROM_SCRIPT=b\n")
    (activate_d / "a.sh").write_text("export FROM_SCRIPT=a\n")
    (activate_d / "a.bat").write_text("set FROM_SCRIPT=a\n")
    (tmp_path / "env.yml").write_text(
        "name: main\nprefix: .conda-envs/main\ndependencies: [python]\n"
    )
    env = {"kind": "conda", "path": "env.yml"}
    return env, str(prefix), str(bin_dir)


def test_conda_activation(tmp_path, monkeypatch):
    env, prefix, bin_dir = _fake_conda_env(tmp_path, monkeypatch)
    activation = env_shell.get_activation("main", env, {"main": env})
    assert bin_dir in activation.path
    assert activation.env_vars["CONDA_PREFIX"] == prefix
    assert activation.env_vars["CONDA_DEFAULT_ENV"] == prefix
    assert activation.env_vars["CONDA_PROMPT_MODIFIER"] == "(main) "
    assert activation.env_vars["MY_VAR"] == "from-conda"
    assert "VIRTUAL_ENV" in activation.unset
    script = env_shell.get_activation_script(activation, "posix")
    # Activation scripts run in name order, after the variables are set
    assert script.index("a.sh") < script.index("b.sh")
    assert script.index("MY_VAR") < script.index("a.sh")
    assert "a.bat" not in script
    assert "a.bat" in env_shell.get_activation_script(activation, "cmd")


def test_conda_activation_not_created(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "env.yml").write_text(
        "name: main\nprefix: .conda-envs/main\ndependencies: [python]\n"
    )
    env = {"kind": "conda", "path": "env.yml"}
    with pytest.raises(ValueError, match="hasn't been created"):
        env_shell.get_activation("main", env, {"main": env})


def test_venv_activation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    bin_name = "Scripts" if sys.platform == "win32" else "bin"
    env = {"kind": "uv", "path": "pyproject.toml"}
    activation = env_shell.get_activation("py", env, {"py": env})
    venv = str(tmp_path / ".venv")
    assert activation.path == [os.path.join(venv, bin_name)]
    assert activation.env_vars == {
        "VIRTUAL_ENV": venv,
        "VIRTUAL_ENV_PROMPT": "py",
    }
    assert activation.unset == ["PYTHONHOME"]
    env = {"kind": "uv-venv", "path": "requirements.txt", "prefix": "v"}
    activation = env_shell.get_activation("py", env, {"py": env})
    assert activation.env_vars["VIRTUAL_ENV"] == str(tmp_path / "v")


def test_unsupported_kind():
    env = {"kind": "julia", "path": "Project.toml"}
    with pytest.raises(ValueError, match="calkit xenv -n jl -- <command>"):
        env_shell.get_activation("jl", env, {"jl": env})


@pytest.mark.parametrize(
    "shell, family",
    [
        ("/bin/bash", "bash"),
        ("/usr/bin/zsh", "zsh"),
        ("/bin/dash", "sh"),
        ("/opt/homebrew/bin/fish", "fish"),
        ("C:\\Program Files\\PowerShell\\7\\pwsh.exe", "powershell"),
        ("powershell.exe", "powershell"),
        ("C:\\Windows\\System32\\cmd.exe", "cmd"),
        ("/usr/bin/nu", "other"),
    ],
)
def test_get_shell_family(shell, family):
    assert env_shell.get_shell_family(shell.replace("\\", os.sep)) == family


def _activation(tmp_path) -> env_shell.Activation:
    return env_shell.Activation(
        name="main",
        path=[str(tmp_path / "env bin")],
        env_vars={"VIRTUAL_ENV": str(tmp_path / "env")},
        unset=["PYTHONHOME"],
    )


def test_prepare(tmp_path):
    activation = _activation(tmp_path)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    base = {"PATH": "/usr/bin", "HOME": str(tmp_path), "ZDOTDIR": "/z"}
    # bash reads the user's bashrc first
    cmd, env = env_shell.prepare("/bin/bash", activation, str(tmpdir), base)
    assert cmd[:2] == ["/bin/bash", "--rcfile"] and cmd[-1] == "-i"
    rc = open(cmd[2]).read()
    assert rc.index(".bashrc") < rc.index("activate.sh")
    assert env["PATH"] == "/usr/bin"
    # zsh is pointed at files that read the user's, from their ZDOTDIR
    cmd, env = env_shell.prepare("/bin/zsh", activation, str(tmpdir), base)
    assert cmd == ["/bin/zsh", "-i"]
    assert env["ZDOTDIR"] == str(tmpdir)
    assert env["CALKIT_USER_ZDOTDIR"] == "/z"
    assert ".zshrc" in (tmpdir / ".zshrc").read_text()
    # fish runs it after its config
    cmd, _ = env_shell.prepare("fish", activation, str(tmpdir), base)
    assert cmd[:2] == ["fish", "-C"]
    script = (tmpdir / "activate.fish").read_text()
    assert "set -gx CALKIT_SHELL 'main'" in script
    assert "set -e PYTHONHOME" in script
    # PowerShell is given it as a command, which no execution policy stops
    cmd, _ = env_shell.prepare("pwsh", activation, str(tmpdir), base)
    assert cmd[:3] == ["pwsh", "-NoExit", "-EncodedCommand"]
    script = base64.b64decode(cmd[3]).decode("utf-16-le")
    assert "$env:CALKIT_SHELL = 'main'" in script
    assert "function global:prompt" in script
    # cmd runs a batch file after its AutoRun
    cmd, _ = env_shell.prepare("cmd.exe", activation, str(tmpdir), base)
    assert cmd[:2] == ["cmd.exe", "/k"]
    script = open(cmd[2]).read()
    assert 'set "CALKIT_SHELL=main"' in script
    assert 'set "PYTHONHOME="' in script
    # A shell this doesn't know starts with the variables set
    cmd, env = env_shell.prepare("nu", activation, str(tmpdir), base)
    assert cmd == ["nu"]
    assert env["PATH"].startswith(str(tmp_path / "env bin") + os.pathsep)
    assert env["CALKIT_SHELL"] == "main"
    assert env["VIRTUAL_ENV"] == str(tmp_path / "env")


def _run_shell(shell, activation, home, commands, extra_env=None):
    """Run a shell non-interactively, with commands on its input."""
    out = {}

    def run(cmd, env):
        res = subprocess.run(
            cmd,
            env=env | (extra_env or {}),
            input=commands,
            capture_output=True,
            text=True,
        )
        out["stdout"] = res.stdout
        return res.returncode

    base = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "PYTHONHOME": "/nowhere",
    }
    status = env_shell.start(shell, activation, base_env=base, run=run)
    return status, out["stdout"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shells")
@pytest.mark.parametrize("name", ["bash", "zsh", "sh"])
def test_start(tmp_path, name):
    shell = shutil.which(name)
    if shell is None:
        pytest.skip(f"{name} isn't installed")
    activation = _activation(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    # Startup files that put something else first on PATH, as activating
    # Conda's base does, run before the environment is activated
    other = "/other/bin"
    for rc in (".bashrc", ".zshrc"):
        (home / rc).write_text(
            f'export PATH="{other}:$PATH"\nexport FROM_RC=1\n'
        )
    status, stdout = _run_shell(
        shell,
        activation,
        home,
        'echo "PATH=$PATH"\necho "VENV=$VIRTUAL_ENV"\n'
        'echo "PYTHONHOME=${PYTHONHOME:-unset}"\n'
        'echo "CALKIT_SHELL=$CALKIT_SHELL"\necho "RC=${FROM_RC:-}"\n'
        "exit 3\n",
    )
    assert status == 3
    lines = dict(
        line.split("=", 1) for line in stdout.splitlines() if "=" in line
    )
    assert lines["PATH"].startswith(str(tmp_path / "env bin") + ":")
    assert lines["VENV"] == str(tmp_path / "env")
    assert lines["PYTHONHOME"] == "unset"
    assert lines["CALKIT_SHELL"] == "main"
    if name != "sh":
        assert lines["RC"] == "1"
        assert other in lines["PATH"]


@pytest.mark.skipif(shutil.which("zsh") is None, reason="Needs zsh")
def test_start_zsh_with_zdotdir(tmp_path):
    activation = _activation(tmp_path)
    home = tmp_path / "home"
    zdotdir = tmp_path / "zdot"
    home.mkdir()
    zdotdir.mkdir()
    (zdotdir / ".zshenv").write_text("export FROM_ZSHENV=1\n")
    (zdotdir / ".zshrc").write_text("export FROM_ZSHRC=1\n")
    status, stdout = _run_shell(
        shutil.which("zsh"),
        activation,
        home,
        'echo "E=$FROM_ZSHENV R=$FROM_ZSHRC Z=$ZDOTDIR"\n',
        extra_env={"ZDOTDIR": str(zdotdir)},
    )
    assert status == 0
    # The user's startup files are read, and ZDOTDIR is theirs again
    assert f"E=1 R=1 Z={zdotdir}" in stdout


def test_start_conda(tmp_path, monkeypatch):
    if shutil.which("bash") is None or sys.platform == "win32":
        pytest.skip("Needs bash")
    env, prefix, bin_dir = _fake_conda_env(tmp_path, monkeypatch)
    activation = env_shell.get_activation("main", env, {"main": env})
    home = tmp_path / "home"
    home.mkdir()
    # Activating base puts its name in the prompt, which this replaces
    (home / ".bashrc").write_text(
        'export CONDA_PROMPT_MODIFIER="(base) "\nPS1="(base) > "\n'
    )
    status, stdout = _run_shell(
        shutil.which("bash"),
        activation,
        home,
        'echo "S=$FROM_SCRIPT V=$MY_VAR"\necho "PS1=$PS1"\n',
    )
    assert status == 0
    assert "S=b V=from-conda" in stdout
    assert "PS1=(main) > " in stdout
