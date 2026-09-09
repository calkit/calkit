"""Tests for the ``core`` module."""

import os
import subprocess
from unittest import mock

import git
import pytest

import calkit


def test_find_project_dirs():
    # TODO: We should setup a dummy project for this test so it doesn't depend
    # on the state of the dev's machine
    calkit.find_project_dirs()
    if os.path.isdir(os.path.join(os.path.expanduser("~"), "calkit")):
        assert calkit.find_project_dirs(relative=False)


def test_to_kebab_case():
    assert calkit.to_kebab_case("THIS IS") == "this-is"
    assert calkit.to_kebab_case("this_is_my-Project") == "this-is-my-project"
    assert calkit.to_kebab_case("this is my project") == "this-is-my-project"
    assert calkit.to_kebab_case("thisIs/myProject") == "thisis-myproject"


def test_detect_project_name(tmp_dir):
    # First check we can detect with no git remote and no calkit.yaml
    # In this case the project name should be the current directory name
    cwd = os.getcwd()
    dir_name = os.path.basename(cwd)
    assert calkit.detect_project_name(prepend_owner=False) == dir_name
    # If prepend_owner is True, this should raise an error
    with pytest.raises(ValueError):
        calkit.detect_project_name(prepend_owner=True)
    # Now create an actual project
    subprocess.check_output(["calkit", "init"])
    repo = git.Repo()
    repo.create_remote("origin", "https://github.com/someone/some-repo.git")
    assert calkit.detect_project_name() == "someone/some-repo"
    with open("calkit.yaml", "w") as f:
        f.write("owner: someone-else\nname: some-project\n")
    assert calkit.detect_project_name() == "someone-else/some-project"
    # calkit.yaml is what a project is, so it wins over a remote that says
    # something else, which is what a fork's remote does
    with open("calkit.yaml", "w") as f:
        f.write("name: some-project\n")
    assert calkit.detect_project_name() == "someone/some-project"
    # Calkit is built around GitHub, but a project on another host still has
    # to be nameable, since its name ends up in image tags and kernel names
    for url, expected in [
        ("https://gitlab.com/a-group/a-repo.git", "a-group/a-repo"),
        ("git@gitlab.com:a-group/sub/a-repo.git", "sub/a-repo"),
        ("ssh://git@git.example.org:2222/a-group/a-repo", "a-group/a-repo"),
    ]:
        with open("calkit.yaml", "w") as f:
            f.write("{}\n")
        repo.remote().set_url(url)
        assert calkit.detect_project_name() == expected


def test_save_calkit_info_preserves_unicode(tmp_dir):
    # Regression: on Windows, opening calkit.yaml without encoding="utf-8"
    # writes as cp1252, which either errors or corrupts non-ASCII content
    # (e.g., the Greek letter "ν") into mojibake ("Î½"). ruamel dumps raw
    # unicode (allow_unicode=True), so the encoding of the file handle matters.
    info = {"name": "p", "owner": "o", "title": "viscosity ν"}
    calkit.save_calkit_info(info)
    # The value must survive the round-trip intact.
    assert calkit.load_calkit_info()["title"] == "viscosity ν"
    # Raw bytes must be the UTF-8 encoding of "ν", not cp1252 mojibake.
    raw = open("calkit.yaml", "rb").read()
    assert "ν".encode("utf-8") in raw
    assert "Î½".encode("utf-8") not in raw


def test_load_calkit_info(tmp_dir, monkeypatch):
    subpath = "some/project"
    os.makedirs(subpath)
    with open(subpath + "/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "name": "some-project",
                "owner": "someone",
                "environments": {
                    "env1": {"kind": "docker", "image": "ubuntu"},
                    "env2": {"kind": "docker", "image": "openfoam"},
                },
            },
            f,
        )
    ck_info = calkit.load_calkit_info(wdir=subpath)
    assert ck_info["name"] == "some-project"
    assert ck_info["environments"]["env1"]["image"] == "ubuntu"
    assert ck_info["environments"]["env2"]["image"] == "openfoam"
    # The working directory is used when no wdir is passed
    monkeypatch.chdir(subpath)
    ck_info = calkit.load_calkit_info()
    assert ck_info["environments"]["env1"]["image"] == "ubuntu"
    assert ck_info["environments"]["env2"]["image"] == "openfoam"
    # A project with no calkit.yaml loads as an empty dict
    os.remove("calkit.yaml")
    assert calkit.load_calkit_info() == {}


def test_get_env_var_dep_names():
    ck_info = {
        "dependencies": [
            {"name": "MY_ENV_VAR", "kind": "env-var"},
            {"name": "MY_APP", "kind": "app"},
            "something-else",
            {"MY_OTHER_ENV_VAR": {"kind": "env-var"}},
        ]
    }
    assert calkit.get_env_var_dep_names(ck_info) == [
        "MY_ENV_VAR",
        "MY_OTHER_ENV_VAR",
    ]


def test_check_system_deps(tmp_dir):
    ck_info = {
        "dependencies": [
            "uv",
            {"kind": "env-var", "name": "MY_ENV_VAR"},
            {"MY_ENV_VAR2": {"kind": "env-var"}},
        ]
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(
        ["calkit", "check", "dependencies"],
        env=os.environ.copy() | {"MY_ENV_VAR": "5", "MY_ENV_VAR2": "55"},
    )
    with pytest.raises(ValueError):
        calkit.check_system_deps()


def test_get_requirements_honors_the_old_key():
    reqs = ["git", {"kind": "cpu-count", "min": 2}]
    assert calkit.get_requirements({"requirements": reqs}) == reqs
    # 'dependencies' is what this key used to be called
    assert calkit.get_requirements({"dependencies": reqs}) == reqs
    assert calkit.get_requirements({}) == []
    # Saying it twice in two places is two places for it to drift apart
    with pytest.raises(ValueError, match="merge them"):
        calkit.get_requirements(
            {"requirements": ["git"], "dependencies": ["uv"]}
        )
    # The old name still works, and says so -- once per process, since a
    # single command reads the list several times over
    calkit.core._warned_deprecated_dependencies_key = False
    with mock.patch("calkit.cli.warn") as warn:
        calkit.get_requirements({"dependencies": reqs})
        calkit.get_requirements({"dependencies": reqs})
        calkit.get_requirements({"requirements": reqs})
    assert warn.call_count == 1
    assert "deprecated" in warn.call_args[0][0]
    # It goes to stderr, so it can't corrupt machine-readable output
    assert warn.call_args.kwargs["err"]
    # Env-var names are read through whichever key was used
    ck_info = {"requirements": [{"name": "MY_VAR", "kind": "env-var"}]}
    assert calkit.get_env_var_dep_names(ck_info) == ["MY_VAR"]


def test_check_property_requirement():
    from calkit.core import check_property_requirement as check

    info = {
        "cpu_count": 8,
        "memory_gb": 32.0,
        "os": "Linux",
        "python_version": "3.12.4",
    }
    # Numeric properties are bounded from either side
    check({"kind": "cpu-count", "min": 8}, info)
    check({"kind": "cpu-count", "max": 8}, info)
    check({"kind": "memory-gb", "min": 16, "max": 64}, info)
    with pytest.raises(ValueError, match="at least 16"):
        check({"kind": "cpu-count", "min": 16}, info)
    with pytest.raises(ValueError, match="at most 4"):
        check({"kind": "cpu-count", "max": 4}, info)
    # A bound is what makes the entry say anything at all
    with pytest.raises(ValueError, match="lock"):
        check({"kind": "cpu-count"}, info)
    with pytest.raises(ValueError, match="lock"):
        check({"kind": "os"}, info)
    # Values match case-insensitively, and a list means any of them
    check({"kind": "os", "equals": "linux"}, info)
    check({"kind": "os", "equals": ["Darwin", "Linux"]}, info)
    with pytest.raises(ValueError, match="'Darwin' is required"):
        check({"kind": "os", "equals": "Darwin"}, info)
    # Versions compare as versions rather than as strings
    check({"kind": "python-version", "version_spec": ">=3.11"}, info)
    with pytest.raises(ValueError, match=">=3.13"):
        check({"kind": "python-version", "version_spec": ">=3.13"}, info)
    with pytest.raises(ValueError, match="can't be read as a version"):
        check({"kind": "os", "version_spec": ">=1"}, info)
    # A property the machine doesn't report is unanswered, not satisfied
    with pytest.raises(ValueError, match="doesn't report it"):
        check({"kind": "cpu-count", "min": 1}, {})
    # The machine an error talks about is the one that was checked
    with pytest.raises(ValueError, match="host 'box' has cpu-count"):
        check(
            {"kind": "cpu-count", "min": 16}, info, described_as="host 'box'"
        )


def test_check_requirements_checks_machine_properties(tmp_dir):
    ck_info = {"requirements": [{"kind": "cpu-count", "min": 1}]}
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    calkit.check_requirements(ck_info=ck_info, interactive=False)
    # A machine that can't meet them stops the run before anything else
    ck_info["requirements"] = [
        {"kind": "cpu-count", "min": 10_000},
        {"kind": "env-var", "name": "NOT_SET_ANYWHERE"},
    ]
    with pytest.raises(ValueError, match="cpu-count"):
        calkit.check_requirements(ck_info=ck_info, interactive=False)
    # An environment's own list is checked in place of the project's
    calkit.check_requirements(
        requirements=[{"kind": "cpu-count", "min": 1}], interactive=False
    )
    # check_system_deps is the old name for the same function
    assert calkit.check_system_deps is calkit.check_requirements


def test_check_app_version():
    from calkit.core import check_app_version, extract_version

    # A version has to be found in whatever the tool prints
    assert extract_version("git version 2.39.5") == "2.39.5"
    assert extract_version("uv 0.4.18 (a1b2c3d 2024-09-20)") == "0.4.18"
    assert extract_version("") is None
    info = {"git_version": "git version 2.39.5"}
    check_app_version("git", ">=2.30", system_info=info)
    check_app_version("git", "2.39.5", system_info=info)
    with pytest.raises(ValueError, match="but '>=3' is required"):
        check_app_version("git", ">=3", system_info=info)
    # An unreadable version is reported rather than failed, since plenty of
    # tools don't answer --version in any parseable way
    check_app_version("mystery", ">=1", system_info={}, probe_locally=False)
    # A version a system description doesn't carry is still read from the
    # machine, unless the machine in question isn't this one
    check_app_version("git", ">=1", system_info={})


def test_check_dep_exists_conda_off_path(monkeypatch):
    # Conda is frequently installed but not on the PATH (especially on
    # Windows). check_dep_exists should locate it via find_conda_exe rather
    # than relying on ``conda --version`` being directly runnable.
    import calkit.conda

    # Simulate conda being absent from the PATH but present in a typical
    # install location that find_conda_exe discovers.
    monkeypatch.setattr(
        calkit.conda, "find_conda_exe", lambda: "/opt/miniconda3/bin/conda"
    )
    monkeypatch.setattr(calkit.conda, "find_mamba_exe", lambda: None)
    assert calkit.check_dep_exists("conda", "app")
    assert not calkit.check_dep_exists("mamba", "app")
    # When neither is findable, it should report missing.
    monkeypatch.setattr(calkit.conda, "find_conda_exe", lambda: None)
    assert not calkit.check_dep_exists("conda", "app")


def test_get_md5(tmp_dir):
    with open("file1.txt", "w") as f:
        f.write("Hello world")
    with open("file2.txt", "w") as f:
        f.write("Hello world")
    assert calkit.get_md5("file1.txt") == calkit.get_md5("file2.txt")
    assert calkit.get_md5("file1.txt") == "3e25960a79dbc69b674cd4ec67a72c62"
    # Try a directory
    os.makedirs("mydir")
    with open("mydir/file3.txt", "w") as f:
        f.write("Hello again")
    with open("mydir/file4.txt", "w") as f:
        f.write("And again")
    dir_hash = calkit.get_md5("mydir")
    assert dir_hash == "edfc5cb4a1b7c90d07bca687716a75cd"
    dir_hash2 = calkit.get_md5("mydir", exclude_files=["file4.txt"])
    assert dir_hash2 == "f06b4641c3014439f44382db77164354"


def test_ryaml_dump_leaves_no_trailing_whitespace():
    # Wrapping must not leave a space before the fold.
    #
    # Whitespace-trimming tools strip those, and Calkit writes them back on
    # the next compile, so the two take turns rewriting the same file.
    import io

    import calkit

    # Value lengths near the wrap width are what trigger it
    for n in range(60, 92):
        buf = io.StringIO()
        data = {"stages": {"s": {"cmd": "python " + "a" * n}}}
        calkit.ryaml.dump(data, buf)
        text = buf.getvalue()
        assert not any(line != line.rstrip() for line in text.splitlines()), (
            f"trailing whitespace at length {n}: {text!r}"
        )
        assert calkit.ryaml.load(text) == data


def test_ryaml_dump_keeps_significant_trailing_whitespace():
    # In a block scalar a trailing space is content, not formatting.
    import io

    from ruamel.yaml.scalarstring import (
        FoldedScalarString,
        LiteralScalarString,
    )

    import calkit

    for value in [
        LiteralScalarString("x \ny\n"),
        FoldedScalarString("x \ny\n"),
    ]:
        buf = io.StringIO()
        calkit.ryaml.dump({"k": value}, buf)
        assert calkit.ryaml.load(buf.getvalue()) == {"k": value}


def test_update_readme_content():
    import calkit

    # A template's README keeps everything but its title, and the
    # description goes right under the new one
    text = "# Template title\n\nSome intro.\n\n```python calkit stage name=a\npass\n```\n"
    out = calkit.update_readme_content(text, "My project", "What it is.")
    assert out == (
        "# My project\n\nWhat it is.\n\nSome intro.\n\n"
        "```python calkit stage name=a\npass\n```\n"
    )
    # No description: only the title changes
    assert calkit.update_readme_content(text, "My project", None) == (
        text.replace("# Template title", "# My project")
    )
    # Only the first top-level heading is the title; '##' is not one
    text = "Intro first.\n\n## Section\n\n# Real title\n\nBody.\n"
    out = calkit.update_readme_content(text, "T", "D.")
    assert out == "Intro first.\n\n## Section\n\n# T\n\nD.\n\nBody.\n"
    # A README with no heading gets one put in front of it
    assert calkit.update_readme_content("Just prose.\n", "T", "D.") == (
        "# T\n\nD.\n\nJust prose.\n"
    )
    assert calkit.update_readme_content("", "T", "D.") == "# T\n\nD.\n"
    assert calkit.update_readme_content("", "T", None) == "# T\n"
