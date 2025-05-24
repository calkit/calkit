"""Tests for the ``core`` module."""

import os
import subprocess

import git

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
    subprocess.check_output(["calkit", "init"])
    repo = git.Repo()
    repo.create_remote("origin", "https://github.com/someone/some-repo.git")
    assert calkit.detect_project_name() == "someone/some-repo"
    with open("calkit.yaml", "w") as f:
        f.write("owner: someone-else\nname: some-project\n")
    assert calkit.detect_project_name() == "someone-else/some-project"


def test_load_calkit_info(tmp_dir):
    subpath = "some/project"
    os.makedirs(subpath)
    os.makedirs(subpath + "/.calkit/environments")
    with open(subpath + "/.calkit/environments/env2.yaml", "w") as f:
        calkit.ryaml.dump({"kind": "docker", "image": "openfoam"}, f)
    with open(subpath + "/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "name": "some-project",
                "owner": "someone",
                "environments": {
                    "env1": {"kind": "docker", "image": "ubuntu"},
                    "env2": {"_include": ".calkit/environments/env2.yaml"},
                },
            },
            f,
        )
    ck_info = calkit.load_calkit_info(wdir=subpath)
    assert ck_info["environments"]["env1"]["image"] == "ubuntu"
    assert ck_info["environments"]["env2"] == {
        "_include": ".calkit/environments/env2.yaml"
    }
    ck_info = calkit.load_calkit_info(wdir=subpath, process_includes=True)
    assert ck_info["environments"]["env1"]["image"] == "ubuntu"
    assert ck_info["environments"]["env2"]["image"] == "openfoam"
    os.chdir(subpath)
    ck_info = calkit.load_calkit_info(process_includes=True)
    assert ck_info["environments"]["env1"]["image"] == "ubuntu"
    assert ck_info["environments"]["env2"]["image"] == "openfoam"
