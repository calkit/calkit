"""Tests for ``calkit.cli.open_``."""

import os
import shutil
import subprocess

from typer.testing import CliRunner

from calkit.cli.main import app

runner = CliRunner()


def test_open_project(tmp_path, monkeypatch):
    import calkit.cli.main.core

    def make_project(path, owner, name=None):
        os.makedirs(path)
        info = f"owner: {owner}\n" + (f"name: {name}\n" if name else "")
        with open(os.path.join(path, "calkit.yaml"), "w") as f:
            f.write(info)
        git = ["git", "-c", "user.name=T", "-c", "user.email=t@example.com"]
        subprocess.check_call([*git, "init", "-q"], cwd=path)
        subprocess.check_call([*git, "add", "-A"], cwd=path)
        subprocess.check_call([*git, "commit", "-qm", "Init"], cwd=path)

    def run(*args):
        opened.clear()
        return runner.invoke(app, ["open", "project", *args])

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    opened: list[str] = []
    real_which = shutil.which
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd, *a, **k: "/bin/code" if cmd == "code" else real_which(cmd),
    )
    real_call = subprocess.call

    def call(cmd, *args, **kwargs):
        if cmd[0] == "/bin/code":
            opened.append(cmd[1])
            return 0
        return real_call(cmd, *args, **kwargs)

    monkeypatch.setattr("subprocess.call", call)
    main = home / "calkit" / "proj"
    make_project(str(main), "me", "proj")
    # A subproject in its repo, which names no project of its own and so
    # gets the repo's from its remote, isn't taken for another copy of it
    subprocess.check_call(
        ["git", "remote", "add", "origin", "https://github.com/me/proj"],
        cwd=main,
    )
    os.makedirs(main / "sub")
    (main / "sub" / "calkit.yaml").write_text("{}\n")
    # A worktree is another checkout of the same project, and the one in
    # ~/calkit is opened over it
    worktree = home / "dev" / "proj-wt"
    os.makedirs(worktree.parent)
    subprocess.check_call(
        ["git", "worktree", "add", "-q", str(worktree)], cwd=main
    )
    for args in [["proj"], ["me/proj"]]:
        result = run(*args)
        assert result.exit_code == 0, result.output
        assert opened == [os.path.realpath(main)]
    # Another owner's project of the same name needs the owner given
    make_project(str(home / "dev" / "proj"), "them", "proj")
    result = run("proj")
    assert result.exit_code != 0
    assert "me/proj" in result.output and "them/proj" in result.output
    result = run("them/proj")
    assert result.exit_code == 0, result.output
    assert opened == [os.path.realpath(home / "dev" / "proj")]
    # A missing project needs an owner to be cloned, and asks first
    result = run("new-proj")
    assert result.exit_code != 0
    assert "OWNER/new-proj" in result.output
    result = run("me/new-proj")
    assert result.exit_code != 0
    assert "--yes" in result.output
    cloned = []

    def fake_clone(url, location):
        cloned.append((url, location))
        make_project(location, "me", "new-proj")

    monkeypatch.setattr(calkit.cli.main.core, "clone", fake_clone)
    result = run("me/new-proj", "--yes")
    assert result.exit_code == 0, result.output
    new_path = os.path.join(str(home), "calkit", "new-proj")
    assert cloned == [("me/new-proj", new_path)]
    assert opened == [new_path]
    # Without VS Code's command, the folder opens instead
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd, *a, **k: None if cmd == "code" else real_which(cmd),
    )
    launched = []
    monkeypatch.setattr("typer.launch", lambda path: launched.append(path))
    result = run("them/proj")
    assert result.exit_code == 0, result.output
    assert launched == [os.path.realpath(home / "dev" / "proj")]
    assert "code" in result.output
