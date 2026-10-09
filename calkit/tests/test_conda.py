"""Tests for the ``conda`` module."""

import os
import re
import shutil
import subprocess
import sys

import pytest

import calkit
from calkit.conda import (
    _check_list,
    _check_single,
    _enrich_pip_deps_from_freeze,
    _get_pip_dependency_list,
    _split_env_dependencies,
    _unparseable_version_satisfies,
    check_env,
    find_conda_exe,
    write_cross_platform_locks,
)

ENV_NAME = "main"

# TODO: calkit conda env subprocess interactions need Windows debugging.
# Conda on Windows uses .bat shims and PATH activation that interact poorly
# with Python's subprocess; needs a real Windows checkout to fix properly.
skipif_windows_conda = pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: calkit conda env subprocess interactions need Windows debug",
)


def test_check_single():
    assert _check_single(
        "python=3.12", "python=3.12.18", env_spec_dir=".", conda=True
    )
    assert _check_single(
        "python=3", "python=3.12.18", env_spec_dir=".", conda=True
    )
    assert _check_single(
        "python=3.12.18", "python=3.12.18", env_spec_dir=".", conda=True
    )
    assert _check_single(
        "python>=3.12,<3.13", "python==3.12.18", env_spec_dir=".", conda=False
    )
    # PEP 508 git direct reference in req matches plain installed version
    assert _check_single(
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@fc0b49b",
        "pyxdsm==0.4.0",
        env_spec_dir=".",
        conda=False,
    )
    # Different package name must not match
    assert not _check_single(
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@fc0b49b",
        "other==1.0",
        env_spec_dir=".",
        conda=False,
    )
    # Both sides git: same ref → match
    assert _check_single(
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@fc0b49b",
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@fc0b49b",
        env_spec_dir=".",
        conda=False,
    )
    # Both sides git: short spec ref matches long installed ref (prefix)
    assert _check_single(
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@fc0b49b",
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@fc0b49b07ca1234",
        env_spec_dir=".",
        conda=False,
    )
    # Both sides git: different refs → no match
    assert not _check_single(
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@fc0b49b",
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@aabbcc1",
        env_spec_dir=".",
        conda=False,
    )
    # Unparseable actual version (e.g. conda's "9e"): equality and inequality
    # are still decidable by comparing version strings, a bare name accepts any
    # version, and an ordering constraint can't be confirmed so it counts as
    # unsatisfied.
    assert _check_single("jpeg", "jpeg=9e", env_spec_dir=".", conda=True)
    assert _check_single("jpeg=9e", "jpeg=9e", env_spec_dir=".", conda=True)
    assert _check_single("jpeg!=1", "jpeg=9e", env_spec_dir=".", conda=True)
    assert not _check_single(
        "jpeg!=9e", "jpeg=9e", env_spec_dir=".", conda=True
    )
    assert not _check_single("jpeg=1", "jpeg=9e", env_spec_dir=".", conda=True)
    # conda's "=1.2" expands to "==1.2.*", and a wildcard needs a parsed
    # version, so it stays unverifiable.
    assert not _check_single(
        "jpeg=1.2", "jpeg=9e", env_spec_dir=".", conda=True
    )
    assert not _check_single(
        "jpeg>=1", "jpeg=9e", env_spec_dir=".", conda=True
    )
    # Pip-style specifiers behave the same way
    assert _check_single("jpeg==9e", "jpeg==9e", env_spec_dir=".", conda=False)
    # "!=" and "~=" must parse the package name correctly, which they didn't
    # when the name was split on "=<>" alone
    assert _check_single(
        "jpeg!=1.0", "jpeg==9.0", env_spec_dir=".", conda=False
    )
    assert not _check_single(
        "jpeg!=9.0", "jpeg==9.0", env_spec_dir=".", conda=False
    )
    assert _check_single(
        "jpeg~=1.0", "jpeg==1.9", env_spec_dir=".", conda=False
    )
    assert not _check_single(
        "jpeg~=1.0", "jpeg==2.0", env_spec_dir=".", conda=False
    )


def test_unparseable_version_satisfies():
    check = _unparseable_version_satisfies
    # No constraint accepts anything
    assert check("", "9e") is True
    # Plain equality and inequality compare as strings
    assert check("==9e", "9e") is True
    assert check("==9e", "9f") is False
    assert check("!=9e", "9e") is False
    assert check("!=9f", "9e") is True
    # PEP 440 arbitrary equality is also a string comparison
    assert check("===9e", "9e") is True
    # Conjunctions hold only if every clause holds
    assert check("==9e,!=9f", "9e") is True
    assert check("==9e,==9f", "9e") is False
    # Wildcards and ordering operators need a parsed version
    assert check("==1.*", "9e") is None
    assert check("!=1.*", "9e") is None
    assert check(">=1", "9e") is None
    assert check("~=1.2", "9e") is None
    # Matching is exact, with no zero-padding
    assert check("==1.0", "1.0.0") is False


def test_enrich_pip_deps_from_freeze():
    pip_freeze = [
        "numpy==1.24.3",
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@fc0b49b07ca",
        "scipy==1.11.0",
    ]
    spec_deps = [
        "numpy==1.24.3",
        "pyxdsm @ git+https://github.com/rebeccamccabe/pyXDSM.git@fc0b49b",
        "scipy",
    ]
    result = _enrich_pip_deps_from_freeze(spec_deps, pip_freeze)
    # numpy and scipy get the exact freeze version
    assert "numpy==1.24.3" in result
    assert "scipy==1.11.0" in result
    # pyxdsm gets the full git URL from freeze
    assert any("fc0b49b07ca" in r for r in result)
    # Editable installs are kept unchanged
    editable = ["-e ../mypackage", "numpy==1.24.3"]
    result2 = _enrich_pip_deps_from_freeze(editable, pip_freeze)
    assert result2[0] == "-e ../mypackage"


def test_check_list():
    installed = ["python=3.12.1", "numpy=1.0.11"]
    assert _check_list("python=3", installed, env_spec_dir=".", conda=True)
    assert _check_list("numpy", installed, env_spec_dir=".", conda=True)
    assert not _check_list("pandas", installed, env_spec_dir=".", conda=True)
    installed = ["python==3.12.1", "numpy==1.0.11"]
    assert _check_list("python>=3", installed, env_spec_dir=".", conda=False)
    assert _check_list("numpy", installed, env_spec_dir=".", conda=False)
    assert not _check_list("pandas", installed, env_spec_dir=".", conda=False)


def test_split_env_dependencies():
    dependencies = [
        "python=3.12",
        "pip",
        "numpy=2",
        {"pip": ["sqlalchemy==2.0.39"]},
    ]
    conda_deps, pip_deps = _split_env_dependencies(dependencies)
    assert conda_deps == ["python=3.12", "pip", "numpy=2"]
    assert pip_deps == ["sqlalchemy==2.0.39"]


def test_get_pip_dependency_list():
    dependencies = ["python=3.12", "pip", {"pip": "sqlalchemy==2.0.39"}]
    pip_deps = _get_pip_dependency_list(dependencies)
    assert pip_deps == ["sqlalchemy==2.0.39"]
    assert dependencies[-1]["pip"] == ["sqlalchemy==2.0.39"]


def delete_env(name: str):
    conda = find_conda_exe() or "conda"
    subprocess.check_call([conda, "env", "remove", "-y", "-n", name])


@pytest.fixture
def conda_env_name():
    name = calkit.to_kebab_case(os.path.basename(os.getcwd())) + "." + ENV_NAME
    yield name
    # Teardown code
    delete_env(name)


@pytest.mark.xdist_group("conda")
@skipif_windows_conda
def test_check_env_locks_every_platform(tmp_dir, conda_env_name):
    import calkit.environments as envs

    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "-n",
            ENV_NAME,
            "--no-check",
            "python=3.12",
            "six",
            "--pip",
            "iniconfig",
        ]
    )
    subprocess.check_call(["calkit", "check", "env", "-n", ENV_NAME])
    lock_dir = os.path.join(".calkit", "env-locks", ENV_NAME)
    here = envs._conda_venv_platform()
    lock_fpath = os.path.join(lock_dir, here + ".yml")

    def spec_is_recorded() -> bool:
        return envs.read_env_spec_hash(lock_fpath) == envs.env_spec_hash(
            "environment.yml"
        )

    def read(fpath: str) -> str:
        with open(fpath) as f:
            return f.read()

    assert spec_is_recorded()
    # Other platforms are solved up front with the versions installed here,
    # so moving to one doesn't add a lock and invalidate every stage
    others = [f for f in os.listdir(lock_dir) if f != here + ".yml"]
    assert others
    with open(lock_fpath) as f:
        six = [d for d in calkit.ryaml.load(f)["dependencies"] if "six=" in d]
    for fname in others:
        text = read(os.path.join(lock_dir, fname))
        assert "iniconfig==" in text
        assert six[0].rsplit("=", 1)[0] + "=" in text
    # A machine without the env creates it from the lock, and leaves the
    # lock as it was, without solving for other platforms again
    before = read(lock_fpath)
    sibling = os.path.join(lock_dir, others[0])
    os.remove(sibling)
    delete_env(conda_env_name)
    subprocess.check_call(["calkit", "check", "env", "-n", ENV_NAME])
    assert read(lock_fpath) == before
    assert not os.path.isfile(sibling)
    # A lock that matches but has no record, e.g., from before records were
    # kept, is adopted as is
    os.remove(envs.ENV_SPEC_HASHES_FPATH)
    subprocess.check_call(["calkit", "check", "env", "-n", ENV_NAME])
    assert spec_is_recorded()
    assert read(lock_fpath) == before
    assert not os.path.isfile(sibling)
    # A relock made on another machine is followed, from the lock
    with open(lock_fpath, "w") as f:
        f.write(re.sub(r"- six=[^\n]*", "- six=1.16.0", before))
    subprocess.check_call(["calkit", "check", "env", "-n", ENV_NAME])
    subprocess.check_call(
        [
            "conda",
            "run",
            "-n",
            conda_env_name,
            "python",
            "-c",
            "import six; assert six.__version__ == '1.16.0'",
        ]
    )
    assert "- six=1.16.0\n" in read(lock_fpath)
    # A changed spec is resolved again everywhere, and a machine without the
    # env creates it from the spec rather than the outdated lock
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "--no-check",
            "python=3.12",
            "six",
            "--pip",
            "iniconfig",
            "--pip",
            "idna",
        ]
    )
    delete_env(conda_env_name)
    subprocess.check_call(["calkit", "check", "env", "-n", ENV_NAME])
    subprocess.check_call(
        ["conda", "run", "-n", conda_env_name, "python", "-c", "import idna"]
    )
    assert spec_is_recorded()
    assert os.path.isfile(sibling)
    for fname in os.listdir(lock_dir):
        assert "idna" in read(os.path.join(lock_dir, fname))


def test_write_cross_platform_locks(tmp_path, monkeypatch):
    import json
    import types

    import calkit.environments as envs

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(envs, "_conda_venv_platform", lambda: "linux-64")
    monkeypatch.setattr(
        envs, "CONDA_VENV_ARCHS", ["linux-64", "osx-arm64", "win-64"]
    )
    monkeypatch.setattr(calkit.conda.shutil, "which", lambda name: "uv")
    for var in ("CONDA_OVERRIDE_OSX", "CONDA_OVERRIDE_GLIBC"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("CONDA_PINNED_PACKAGES", raising=False)
    solves: dict[str, tuple[list, dict]] = {}
    compiles: list[tuple[list[str], list[str] | None]] = []
    failing: set[str] = set()
    failing_pinned: set[str] = set()

    def fake_run(
        cmd: list[str], capture_output: bool, text: bool, env: dict
    ) -> types.SimpleNamespace:
        arch = env["CONDA_SUBDIR"]
        solves[arch] = (cmd, env)
        if arch in failing or (
            arch in failing_pinned and "CONDA_PINNED_PACKAGES" in env
        ):
            return types.SimpleNamespace(stdout='{"error": "unsolvable"}')
        links = [
            {"name": "python", "version": "3.12.11", "build_string": "h_0"},
            {"name": "six", "version": "1.17.0", "build_string": "pyh_0"},
            {"name": "numpy", "version": "2.3.0", "build_string": "py_0"},
        ]
        return types.SimpleNamespace(
            stdout=json.dumps({"actions": {"LINK": links}})
        )

    def fake_compile(
        pip_deps: list[str],
        target: str,
        python: str | None,
        constraints: list[str] | None = None,
    ) -> list[str]:
        compiles.append((pip_deps, constraints))
        return ["iniconfig==2.1.0", "NumPy==2.3.0"]

    monkeypatch.setattr(calkit.conda.subprocess, "run", fake_run)
    monkeypatch.setattr(calkit.conda, "_compile_pip_deps", fake_compile)

    def write_spec(pip_deps: list[str]) -> None:
        spec = {
            "name": "main",
            "channels": ["conda-forge"],
            "dependencies": ["python=3.12", "six", "numpy", {"pip": pip_deps}],
        }
        with open("environment.yml", "w") as f:
            calkit.ryaml.dump(spec, f)

    def write_local(pip_locked: list[str]) -> None:
        local = {
            "name": "main",
            "channels": ["conda-forge"],
            "dependencies": [
                "python=3.12.11=h_0",
                "six=1.17.0=pyh_0",
                "numpy=2.3.0=py_0",
                "libzlib=1.3.1=h_0",
                {"pip": pip_locked},
            ],
        }
        with open(os.path.join("locks", "linux-64.yml"), "w") as f:
            calkit.ryaml.dump(local, f)

    def read(fpath: str) -> str:
        with open(fpath) as f:
            return f.read()

    def locks(relock: bool = True) -> list[str]:
        return write_cross_platform_locks(
            env_fpath="environment.yml",
            lock_fpath=os.path.join("locks", "linux-64.yml"),
            conda_exe="conda",
            log_func=print,
            relock=relock,
        )

    os.makedirs("locks")
    write_spec(["iniconfig"])
    write_local(["iniconfig==2.1.0", "packaging==25.0"])
    osx = os.path.join("locks", "osx-arm64.yml")
    win = os.path.join("locks", "win-64.yml")
    with open(osx, "w") as f:
        f.write("name: main\ndependencies: [python=3.12.10=hosx_0]\n")
    # Relocking solves every other platform, an existing lock included
    assert locks() == [osx, win]
    assert "hosx_0" not in read(osx)
    assert solves["osx-arm64"][1]["CONDA_OVERRIDE_OSX"] == "11.0"
    # Direct dependencies are pinned to the versions installed here, and
    # every other package is held to them where the solve needs it
    cmd, env = solves["win-64"]
    assert cmd[-3:] == ["python==3.12.11", "six==1.17.0", "numpy==2.3.0"]
    assert "libzlib==1.3.1" in env["CONDA_PINNED_PACKAGES"].split("&")
    assert "CONDA_OVERRIDE_OSX" not in env
    assert "CONDA_OVERRIDE_GLIBC" not in env
    assert compiles[-1] == (
        ["iniconfig==2.1.0"],
        ["iniconfig==2.1.0", "packaging==25.0"],
    )
    # The lock leaves to conda what conda installs
    with open(win) as f:
        lock = calkit.ryaml.load(f)
    assert lock["name"] == "main"
    assert "six=1.17.0=pyh_0" in lock["dependencies"]
    assert lock["dependencies"][-1] == {"pip": ["iniconfig==2.1.0"]}
    # Without relocking, only missing platforms are solved
    solves.clear()
    assert locks(relock=False) == []
    assert solves == {}
    os.remove(win)
    assert locks(relock=False) == [win]
    assert list(solves) == ["win-64"]
    # A platform without some version locked here is solved without them
    failing_pinned.add("win-64")
    assert locks() == [osx, win]
    assert "CONDA_PINNED_PACKAGES" not in solves["win-64"][1]
    failing_pinned.clear()
    # Relocking removes a lock that can't be solved again, since it's stale,
    # but otherwise a missing one is left for its own machine
    failing.add("win-64")
    assert locks() == [osx]
    assert not os.path.isfile(win)
    assert locks(relock=False) == []
    failing.clear()
    # A git dependency is pinned to the commit locked here, but an editable
    # one names a path on this machine
    git_dep = "pyxdsm @ git+https://github.com/x/pyXDSM.git@fc0b49b"
    locked_git = git_dep.replace("fc0b49b", "fc0b49b31552f3ed")
    write_local(["iniconfig==2.1.0", locked_git])
    write_spec(["iniconfig", git_dep])
    assert locks() == [osx, win]
    assert compiles[-1][0] == ["iniconfig==2.1.0", locked_git]
    write_spec(["iniconfig", "-e ./pkg"])
    assert locks() == []
    assert not os.path.isfile(osx) and not os.path.isfile(win)
    # Solving on the same OS assumes nothing about its virtual packages
    write_spec(["iniconfig"])
    monkeypatch.setattr(
        envs, "CONDA_VENV_ARCHS", ["linux-64", "linux-aarch64"]
    )
    assert locks() == [os.path.join("locks", "linux-aarch64.yml")]
    assert "CONDA_OVERRIDE_GLIBC" not in solves["linux-aarch64"][1]
    # Only a per-platform lock has siblings
    monkeypatch.setattr(envs, "_conda_venv_platform", lambda: "osx-64")
    assert locks() == []


@pytest.mark.xdist_group("conda")
@skipif_windows_conda
def test_check_env(tmp_dir, conda_env_name):
    subprocess.check_call(["calkit", "init"])
    # Note the specs here use trivial packages, since what matters is that
    # there's one in the conda section and one in the pip section, not which
    # ones---heavier packages cost tens of seconds each to install
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "-n",
            ENV_NAME,
            "--no-check",
            "python=3.13",
            "pip",
            "six",
            "--pip",
            "iniconfig",
        ]
    )
    res = check_env()
    print("Res before env exists:", res)
    assert not res.env_exists
    res = check_env(log_func=print)
    print("Res after env created:", res)
    assert res.env_exists
    assert not res.env_needs_export
    assert not res.env_needs_rebuild
    # Now let's update the env spec so it needs a rebuild
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "--no-check",
            "python=3.11.0",
            "pip",
            "--pip",
            "iniconfig",
        ]
    )
    res = check_env()
    assert res.env_exists
    assert res.env_needs_export
    assert res.env_needs_rebuild
    res = check_env()
    assert not res.env_needs_rebuild
    assert not res.env_needs_export
    # Check relaxed mode, where we allow dependencies to be in either the pip
    # or conda section
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "--no-check",
            "python=3.11.0",
            "pip",
            "sqlalchemy",
        ]
    )
    subprocess.check_call(
        [
            "conda",
            "run",
            "-n",
            conda_env_name,
            "pip",
            "install",
            "--upgrade",
            "sqlalchemy",
        ]
    )
    res = check_env()
    assert res.env_needs_rebuild
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "--no-check",
            "python=3.11.0",
            "pip",
            "sqlalchemy",
        ]
    )
    res = check_env(relaxed=True)
    assert not res.env_needs_rebuild
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "--no-check",
            "python=3.11.0",
            "pip",
            "--pip",
            "sqlalchemy",
        ]
    )
    res = check_env(relaxed=True)
    assert not res.env_needs_rebuild
    # Make sure we can handle other ways of specifying versions
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "--no-check",
            "python=3.12",
            "--pip",
            "numpy>=1",
        ]
    )
    res = check_env()
    assert res.env_needs_rebuild
    res = check_env()
    assert not res.env_needs_export
    assert not res.env_needs_rebuild


@pytest.fixture
def conda_env_prefix():
    prefix = ".conda-envs/my-conda-env"
    yield prefix
    conda = find_conda_exe() or "conda"
    subprocess.check_call([conda, "env", "remove", "-y", "--prefix", prefix])


@pytest.mark.xdist_group("conda")
@skipif_windows_conda
def test_check_prefix_env(tmp_dir, conda_env_prefix):
    subprocess.check_call(["calkit", "init"])
    # Test we can use a local prefix
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "-n",
            "my-conda-env",
            "python=3.12",
            "--prefix",
            conda_env_prefix,
            "--no-check",
        ]
    )
    res = check_env()
    assert not res.env_exists
    assert res.env_needs_export
    assert os.path.isfile(os.path.join(conda_env_prefix, "env-export.yml"))
    res = check_env()
    assert res.env_exists
    # Env will need to be exported a second time since we save it inside the
    # prefix folder, so the mtime will be slightly after creation of the
    # initial environment
    assert res.env_needs_export
    assert not res.env_needs_rebuild
    # Now the env should be exported okay
    res = check_env()
    assert res.env_exists
    assert not res.env_needs_export
    assert not res.env_needs_rebuild
    subprocess.check_call(
        ["calkit", "xenv", "-n", "my-conda-env", "python", "--version"]
    )
    # Test that we can add a new dependency
    with open("environment.yml") as f:
        env = calkit.ryaml.load(f)
    env["dependencies"].append("requests")
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump(env, f)
    res = check_env()
    assert res.env_exists
    assert res.env_needs_export
    assert res.env_needs_rebuild
    subprocess.check_call(
        [
            "calkit",
            "xenv",
            "-n",
            "my-conda-env",
            "python",
            "-c",
            "import requests",
        ]
    )
    # Test that we can specify --wdir
    os.makedirs("subdir")
    subprocess.check_call(
        [
            "calkit",
            "xenv",
            "--wdir",
            "subdir",
            "-n",
            "my-conda-env",
            "python",
            "-c",
            "import requests",
        ]
    )


@pytest.mark.xdist_group("conda")
@skipif_windows_conda
def test_check_env_editable(tmp_dir, conda_env_name):
    subprocess.check_call(["calkit", "init"])
    # Create a dummy package named 'src' to install in editable mode
    os.makedirs("src", exist_ok=True)
    with open("src/__init__.py", "w") as f:
        f.write("def hello():\n    return 'Hello, World!'\n")
    with open("setup.py", "w") as f:
        f.write(
            """from setuptools import setup, find_packages
setup(
    name="src",
    version="0.0.1",
    packages=find_packages(),
)
"""
        )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "-n",
            ENV_NAME,
            "--no-check",
            "python=3.12",
            "pip",
            "six",
            "--pip",
            "-e .",
        ]
    )
    res = check_env()
    assert not res.env_exists
    # Make sure we actually installed in editable mode by checking for
    # src.egg-info
    assert os.path.isdir("src.egg-info")
    res = check_env()
    assert res.env_exists
    assert not res.env_needs_rebuild
    # Check that the lock file has the editable syntax, not the package name
    with open("environment-lock.yml") as f:
        lock = calkit.ryaml.load(f)
    pip_deps = lock["dependencies"][-1]["pip"]
    assert "-e ." in pip_deps
    # Now let's make sure we get proper output if the editable package is
    # has an invalid pyproject.toml
    os.remove("setup.py")
    shutil.rmtree("src.egg-info")
    toml_txt = """[build-system]
requires = ["setuptools>=61.0.0", "wheel", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
name = "src-thing"
dynamic = ["version"]
authors = [
  {name = "Someone"}
]
description = "Test"

dependencies = [
    "numpy>=1.21",
    "scipy>=1.7",
    "pandas>=1.5",
    "matplotlib>=3.5",
    "h5netcdf>=0.12",
    "h5py>=3.0",
    "xarray>=2023.0",
    "streamlit>=1.0"
]

[tool.setuptools]
package-dir = {"" = "src"}
packages = ["src-thing"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
"src-thing" = [] # Explicitly state no package data

[tool.setuptools_scm]
local_scheme = "no-local-version"
fallback_version = "0+unknown"
"""
    with open("pyproject.toml", "w") as f:
        f.write(toml_txt)
    with pytest.raises(Exception, match="Failed to load pyproject.toml"):
        res = check_env()
    # Fix it and make sure it runs with relaxed mode
    toml_txt = """[build-system]
requires = ["setuptools>=61.0.0", "wheel", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
name = "src-thing"
dynamic = ["version"]
authors = [
  {name = "Someone"}
]
description = "Test"

dependencies = []

[tool.setuptools]
packages = ["src"]

[tool.setuptools_scm]
local_scheme = "no-local-version"
fallback_version = "0+unknown"
"""
    with open("pyproject.toml", "w") as f:
        f.write(toml_txt)
    res = check_env(relaxed=True)
    assert res.env_exists
    assert res.env_needs_rebuild
    assert res.env_needs_export
    # Make sure we can import the editable package
    os.makedirs("subdir")
    subprocess.check_call(
        [
            "conda",
            "run",
            "-n",
            conda_env_name,
            "python",
            "-c",
            "import src; print('src file:', src.__file__);",
        ],
        cwd="subdir",
    )
    # Check again and make sure we don't need a rebuild since the editable
    # package is still valid
    res = check_env(relaxed=True)
    assert res.env_exists
    assert not res.env_needs_rebuild


def test_find_conda_exe():
    conda_exe = calkit.conda.find_conda_exe()
    assert conda_exe is not None
    assert os.path.isfile(conda_exe)


def test_find_mamba_exe():
    mamba_exe = calkit.conda.find_mamba_exe()
    # Mamba may not be installed, so we just check that it returns None or a
    # valid path
    if mamba_exe is not None:
        assert os.path.isfile(mamba_exe)
