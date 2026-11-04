"""Tests for ``calkit.cli.open_``."""

import json
import os
import shutil
import subprocess

from typer.testing import CliRunner

from calkit.cli.main import app

runner = CliRunner()


def test_open_project(tmp_path, monkeypatch):
    import calkit.cli.main.core
    import calkit.config

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
    # Windows reads the home folder from here
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(
        calkit.config,
        "read",
        lambda: calkit.config.Settings(default_editor="vscode"),
    )
    opened: list[list[str]] = []
    # Editors are never looked up or launched for real; those "installed"
    # are found in a fake bin folder
    all_editors = ["code", "jupyter", "cursor"]
    editors = list(all_editors)
    real_which = shutil.which

    def which(cmd, *args, **kwargs):
        if cmd in all_editors:
            return f"/fake/bin/{cmd}" if cmd in editors else None
        return real_which(cmd, *args, **kwargs)

    monkeypatch.setattr("shutil.which", which)
    real_call = subprocess.call

    def call(cmd, *args, **kwargs):
        assert os.path.basename(cmd[0]) not in all_editors or cmd[
            0
        ].startswith("/fake/bin/"), cmd
        if cmd[0].startswith("/fake/bin/"):
            opened.append(cmd)
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
        assert opened == [["/fake/bin/code", os.path.realpath(main)]]
    # Another owner's project of the same name needs the owner given
    make_project(str(home / "dev" / "proj"), "them", "proj")
    result = run("proj")
    assert result.exit_code != 0
    assert "me/proj" in result.output and "them/proj" in result.output
    result = run("them/proj")
    assert result.exit_code == 0, result.output
    assert opened == [
        ["/fake/bin/code", os.path.realpath(home / "dev" / "proj")]
    ]
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
    assert opened == [["/fake/bin/code", new_path]]
    # The default editor can be another one we know or any command
    for editor, cmd in [
        ("jupyterlab", ["/fake/bin/jupyter", "lab"]),
        ("cursor --new-window", ["/fake/bin/cursor", "--new-window"]),
    ]:
        monkeypatch.setattr(
            calkit.config,
            "read",
            lambda editor=editor: calkit.config.Settings(
                default_editor=editor
            ),
        )
        result = run("me/new-proj")
        assert result.exit_code == 0, result.output
        assert opened == [[*cmd, new_path]]
    monkeypatch.setattr(
        calkit.config,
        "read",
        lambda: calkit.config.Settings(default_editor="vscode"),
    )
    # Without VS Code, and no terminal to ask in, the folder opens instead
    editors.clear()
    real_isfile = os.path.isfile
    monkeypatch.setattr(
        "os.path.isfile",
        lambda p: (
            "VS Code" not in str(p)
            and "Visual Studio" not in str(p)
            and real_isfile(p)
        ),
    )
    launched = []
    monkeypatch.setattr("typer.launch", lambda path: launched.append(path))
    monkeypatch.setattr("calkit.core.is_tty", lambda: False)
    result = run("them/proj")
    assert result.exit_code == 0, result.output
    assert launched == [os.path.realpath(home / "dev" / "proj")]
    assert "calkit install code" in result.output or "VS Code" in result.output
    # With one, it offers to install VS Code, and with Calkit's extensions
    # and settings, those it doesn't already have set
    import calkit.install

    def fake_install(app):
        editors.append(app)
        return True

    monkeypatch.setattr("calkit.core.is_tty", lambda: True)
    monkeypatch.setattr(
        calkit.install, "get_installer", lambda app: {"script": "fake"}
    )
    monkeypatch.setattr(calkit.install, "install", fake_install)
    monkeypatch.setenv("APPDATA", str(home / "AppData"))
    settings_dir = {
        "mac": home / "Library" / "Application Support" / "Code" / "User",
        "windows": home / "AppData" / "Code" / "User",
    }.get(
        calkit.install._current_platform(), home / ".config" / "Code" / "User"
    )
    os.makedirs(settings_dir)
    (settings_dir / "settings.json").write_text('{"git.autofetch": false}')
    for choice in ["4", "3", "1", "2"]:
        editors.clear()
        launched.clear()
        opened.clear()
        result = runner.invoke(
            app, ["open", "project", "them/proj"], input=choice + "\n"
        )
        assert result.exit_code == 0, result.output
        proj = os.path.realpath(home / "dev" / "proj")
        if choice == "4":
            assert launched == [proj] and not editors
            continue
        if choice == "3":
            assert launched[0].startswith("https://code.visualstudio.com/")
            assert launched[1:] == [proj] and not editors
            continue
        assert opened[-1] == ["/fake/bin/code", proj]
        extensions = [c for c in opened if "--install-extension" in c]
        assert bool(extensions) == (choice == "2")
    assert "Calkit.calkit-vscode" in extensions[0]
    settings = json.loads((settings_dir / "settings.json").read_text())
    assert settings["git.autofetch"] is False
    assert settings["workbench.editorAssociations"]["*.pdf"]
