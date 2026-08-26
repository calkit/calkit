"""Tests for ``calkit.cli.check``."""

import json
import os
import shutil
import socket
import subprocess
import sys
import time

import pytest

import calkit


def test_check_venv(tmp_dir):
    with open("reqs.txt", "w") as f:
        f.write("requests")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    # Now check that we can install from the lock file
    shutil.rmtree(".venv")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open("lock.txt") as f:
        lock_txt = f.read()
    # Now check that if we add a requirement, the env is rebuilt
    assert "polars" not in lock_txt
    with open("reqs.txt", "w") as f:
        f.write("requests\npolars")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open("lock.txt") as f:
        lock_txt = f.read()
    assert "polars" in lock_txt
    # Now confirm that if we check the env again, nothing happens
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open("lock.txt") as f:
        lock_txt_2 = f.read()
    assert lock_txt == lock_txt_2
    # Now check that if we pin a version in reqs.txt, we rebuild
    with open("reqs.txt", "w") as f:
        f.write("requests\npolars==1.0.0")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open("lock.txt") as f:
        lock_txt_3 = f.read()
    assert "polars==1.0.0" in lock_txt_3
    # Test that if we specify a different Python or otherwise fail with an
    # existing prefix, we can still build the environment since it will be
    # deleted and recreated
    subprocess.check_call(
        [
            "calkit",
            "check",
            "venv",
            "reqs.txt",
            "-o",
            "lock.txt",
            "--python",
            "3.11",
        ]
    )


def test_check_venv_moved(tmp_dir):
    with open("reqs.txt", "w") as f:
        f.write("requests")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    # Simulate the project having been renamed, which leaves the old absolute
    # path baked into the activate script
    if sys.platform == "win32":
        activate_fpath = os.path.join(".venv", "Scripts", "activate.bat")
    else:
        activate_fpath = os.path.join(".venv", "bin", "activate")
    with open(activate_fpath) as f:
        activate_txt = f.read()
    prefix = os.path.abspath(".venv")
    assert prefix in activate_txt
    with open(activate_fpath, "w") as f:
        f.write(activate_txt.replace(prefix, os.path.abspath("old-name")))
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open(activate_fpath) as f:
        assert os.path.normcase(prefix) in os.path.normcase(f.read())
    # Activating should now resolve to the env's own Python, which is what
    # breaks when the path is stale
    if sys.platform == "win32":
        cmd = f'call "{activate_fpath}" && python -c "import requests"'
    else:
        cmd = f". \"{activate_fpath}\" && python -c 'import requests'"
    subprocess.check_call(cmd, shell=True)


def test_check_env_vars(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = {
        "dependencies": [
            {"name": "MY_ENV_VAR", "kind": "env-var"},
            {"name": "MY_APP", "kind": "app"},
            "something-else",
            {"MY_OTHER_ENV_VAR": {"kind": "env-var"}},
        ]
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(
        ["calkit", "check", "env-vars"],
        env=os.environ.copy()
        | {"MY_ENV_VAR": "value1", "MY_OTHER_ENV_VAR": "value2"},
    )
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            ["calkit", "check", "env-vars"],
            env=os.environ.copy() | {"MY_ENV_VAR": "value1"},
        )


@pytest.mark.skipif(
    shutil.which("julia") is None, reason="Julia not installed"
)
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Julia env init fails on Windows GHA runners (Pkg stdlib missing)",
)
def test_check_julia_env_caches_second_run(tmp_dir):
    """Second run of ``calkit check julia-env`` should skip Pkg.instantiate."""
    with open("Project.toml", "w") as f:
        f.write('[deps]\n\n[compat]\njulia = "1"\n')
    # The cache includes a signature of the Julia depot, so another test
    # installing packages into the shared depot while this one runs would
    # invalidate it. Write to our own depot, keeping the shared one on the
    # path so packages and registries in it can still be read.
    depot = os.path.join(os.getcwd(), "julia-depot")
    os.makedirs(depot, exist_ok=True)
    env = os.environ.copy() | {
        "JULIA_DEPOT_PATH": os.pathsep.join(
            [depot, os.path.join(os.path.expanduser("~"), ".julia")]
        )
    }
    # First run — should actually call Pkg.instantiate
    result1 = subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml", "--verbose"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert "skipping Pkg.instantiate" not in result1.stdout
    # Second run — nothing has changed, so instantiate should be skipped
    result2 = subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml", "--verbose"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert "skipping Pkg.instantiate" in result2.stdout
    # Modify Project.toml — cache should be invalidated
    with open("Project.toml", "a") as f:
        f.write("# touched\n")
    result3 = subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml", "--verbose"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert "skipping Pkg.instantiate" not in result3.stdout


@pytest.mark.skipif(
    shutil.which("julia") is None, reason="Julia not installed"
)
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Julia env init fails on Windows GHA runners (Pkg stdlib missing)",
)
def test_check_julia_env_repairs_stale_manifest(tmp_dir):
    # A manifest that no longer matches its project---a dependency added
    # after it was locked, say---installs as-is and then fails at
    # precompile, so the check has to resolve it back into line. A
    # current manifest must NOT be resolved: that consults the registry
    # (which can fail spuriously) and can rewrite the lock.
    with open("Project.toml", "w") as f:
        f.write('[deps]\n\n[compat]\njulia = "1"\n')
    depot = os.path.join(os.getcwd(), "julia-depot")
    os.makedirs(depot, exist_ok=True)
    env = os.environ.copy() | {
        "JULIA_DEPOT_PATH": os.pathsep.join(
            [depot, os.path.join(os.path.expanduser("~"), ".julia")]
        )
    }
    subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert os.path.isfile("Manifest.toml")
    # Now the project grows a dependency the manifest knows nothing about
    with open("Project.toml", "w") as f:
        f.write(
            "[deps]\n"
            'Example = "7876af07-990d-54b4-ab0e-23690620f79a"\n\n'
            "[compat]\n"
            'julia = "1"\n'
        )
    result = subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    with open("Manifest.toml") as f:
        assert "Example" in f.read()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Docker daemon not available on windows-latest GHA runners",
)
def test_check_docker_env(tmp_dir):
    # First create a Dockerfile with a known base image
    with open("Dockerfile", "w") as f:
        f.write("FROM python:3.9-slim\n")
    # Now check the environment
    subprocess.check_call(
        [
            "calkit",
            "check",
            "docker-env",
            "python-3.9-slim",
            "-i",
            "Dockerfile",
            "-o",
            "Dockerfile-lock.json",
        ]
    )
    with open("Dockerfile-lock.json") as f:
        lock = json.load(f)
    assert lock["RepoTags"] == ["python-3.9-slim"]
    # An image built here and never pushed anywhere has a digest no registry
    # can serve, which would send anyone reading the lock on a failed pull
    assert lock["RepoDigests"] == []
    # Checking again with nothing changed must not rebuild, and must leave
    # the lock byte-identical so no stage using it reruns
    with open("Dockerfile-lock.json", "rb") as f:
        lock_bytes = f.read()
    subprocess.check_call(
        [
            "calkit",
            "check",
            "docker-env",
            "python-3.9-slim",
            "-i",
            "Dockerfile",
            "-o",
            "Dockerfile-lock.json",
        ]
    )
    with open("Dockerfile-lock.json", "rb") as f:
        assert f.read() == lock_bytes
    # Changing the Dockerfile must invalidate the lock rather than reuse the
    # image it identifies
    with open("Dockerfile", "w") as f:
        f.write("FROM python:3.9-slim\nRUN touch /changed\n")
    subprocess.check_call(
        [
            "calkit",
            "check",
            "docker-env",
            "python-3.9-slim",
            "-i",
            "Dockerfile",
            "-o",
            "Dockerfile-lock.json",
        ]
    )
    with open("Dockerfile-lock.json") as f:
        new_lock = json.load(f)
    assert new_lock["DockerfileMD5"] != lock["DockerfileMD5"]
    assert new_lock["RootFS"]["Layers"] != lock["RootFS"]["Layers"]
    # Renaming the image must do the same, since the lock's digest identifies
    # the image built for the old name
    subprocess.check_call(
        [
            "calkit",
            "check",
            "docker-env",
            "python-3.9-slim-renamed",
            "-i",
            "Dockerfile",
            "-o",
            "Dockerfile-lock.json",
        ]
    )
    with open("Dockerfile-lock.json") as f:
        renamed_lock = json.load(f)
    assert renamed_lock["RepoTags"] == ["python-3.9-slim-renamed"]
    # Now modify the image to fail to build and ensure the lock file is deleted
    with open("Dockerfile", "w") as f:
        f.write("FROM non-existent-image:latest\n")
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            [
                "calkit",
                "check",
                "docker-env",
                "python-3.9-slim",
                "-i",
                "Dockerfile",
                "-o",
                "Dockerfile-lock.json",
            ]
        )
    assert not os.path.exists("Dockerfile-lock.json")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Docker daemon not available on windows-latest GHA runners",
)
def test_check_docker_env_locks_every_platform(tmp_dir):
    from calkit.environments import get_docker_arch

    arch = get_docker_arch()
    other_arch = "amd64" if arch != "amd64" else "arm64"
    argv = [
        "calkit",
        "check",
        "docker-env",
        "alpine:3.18",
        "-o",
        f"locks/{arch}.json",
        "--lock-arch",
        "amd64",
        "--lock-arch",
        "arm64",
    ]
    subprocess.check_call(argv)
    # Both platforms get locked from this one machine, so moving the project
    # to the other doesn't invalidate every stage in the environment
    with open(f"locks/{arch}.json") as f:
        mine = json.load(f)
    with open(f"locks/{other_arch}.json") as f:
        theirs = json.load(f)
    assert mine["Architecture"] == arch
    assert theirs["Architecture"] == other_arch
    assert mine["RootFS"]["Layers"] != theirs["RootFS"]["Layers"]
    # Both name the same multi-platform index, which is what makes either
    # one pullable from either machine
    assert mine["RepoDigests"] == theirs["RepoDigests"]
    assert mine["RepoDigests"]
    # Deleting the image must bring it back by the digest in the lock rather
    # than by tag, and must leave the lock files untouched
    with open(f"locks/{arch}.json", "rb") as f:
        lock_bytes = f.read()
    subprocess.check_call(["docker", "rmi", "-f", "alpine:3.18"])
    out = subprocess.check_output(argv, text=True)
    assert "Pulling image by digest" in out
    with open(f"locks/{arch}.json", "rb") as f:
        assert f.read() == lock_bytes


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Docker daemon not available on windows-latest GHA runners",
)
def test_check_docker_env_pulls_from_registry_instead_of_rebuilding(tmp_dir):
    container = "calkit-test-registry"
    registry = "localhost:5678"
    subprocess.run(["docker", "rm", "-f", container], capture_output=True)
    started = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container,
            "-p",
            "5678:5000",
            "registry:2",
        ],
        capture_output=True,
    )
    if started.returncode != 0:
        pytest.skip("Could not start a local registry")
    try:
        for _ in range(30):
            up = subprocess.run(
                ["docker", "exec", container, "true"], capture_output=True
            )
            if up.returncode == 0:
                break
            time.sleep(1)
        with open("Dockerfile", "w") as f:
            f.write("FROM alpine:3.18\nRUN echo hi > /hi.txt\n")
        argv = [
            "calkit",
            "check",
            "docker-env",
            "calkit-registry-test",
            "-i",
            "Dockerfile",
            "-o",
            "lock.json",
            "--registry",
            f"{registry}/proj",
        ]
        # An image built before a registry was configured must reach it
        # without a rebuild, or an existing project could only publish what
        # it already has by throwing it away first
        subprocess.check_call(argv[:-2])
        with open("lock.json") as f:
            assert json.load(f)["RepoDigests"] == []
        out = subprocess.check_output(argv, text=True)
        assert "Pushing image" in out
        assert "exporting layers" not in out
        with open("lock.json") as f:
            lock = json.load(f)
        # Having been pushed, the image is identified by a digest that can be
        # pulled back, which is what makes a rebuild unnecessary
        assert lock["RepoDigests"] == [
            f"{registry}/proj/calkit-registry-test@"
            + lock["RepoDigests"][0].split("@")[1]
        ]
        with open("lock.json", "rb") as f:
            lock_bytes = f.read()
        subprocess.check_call(
            [
                "docker",
                "rmi",
                "-f",
                "calkit-registry-test",
                f"{registry}/proj/calkit-registry-test:latest",
            ]
        )
        out = subprocess.check_output(argv, text=True)
        assert "Pulling image by digest" in out
        assert "Pushing image" not in out
        # Coming back from the registry has to leave the lock exactly as it
        # was, or every stage in the environment reruns for nothing
        with open("lock.json", "rb") as f:
            assert f.read() == lock_bytes
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        subprocess.run(
            ["docker", "rmi", "-f", "calkit-registry-test"],
            capture_output=True,
        )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Docker daemon not available on windows-latest GHA runners",
)
def test_push_sends_docker_images_to_their_registry(tmp_dir):
    container = "calkit-test-registry-push"
    registry = "localhost:5679"
    subprocess.run(["docker", "rm", "-f", container], capture_output=True)
    started = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container,
            "-p",
            "5679:5000",
            "registry:2",
        ],
        capture_output=True,
    )
    if started.returncode != 0:
        pytest.skip("Could not start a local registry")
    image = "calkit-push-test"
    try:
        subprocess.check_call(["calkit", "init"])
        with open("Dockerfile", "w") as f:
            f.write("FROM alpine:3.18\nRUN echo pushed > /hi.txt\n")
        subprocess.check_call(["docker", "build", "-t", image, "."])
        ck_info = calkit.load_calkit_info()
        ck_info["environments"] = {
            "main": {
                "kind": "docker",
                "path": "Dockerfile",
                "image": image,
                "registry": f"{registry}/proj",
            },
            # An environment named after someone else's image is already
            # somewhere it can be pulled back from, so it isn't pushed
            "tex": {"kind": "docker", "image": "alpine:3.18"},
        }
        calkit.save_calkit_info(ck_info)
        # Tagging an image for a registry gives it a digest under that repo
        # locally, so a push that never happened must not look like one that
        # did, or every later push is skipped
        subprocess.check_call(
            ["docker", "tag", image, f"{registry}/proj/{image}:latest"]
        )
        out = subprocess.check_output(
            ["calkit", "push", "--no-git", "--no-dvc"], text=True
        )
        assert f"Pushing image for 'main' to {registry}/proj/" in out
        assert "tex" not in out
        # Once the registry really has it, pushing again sends nothing
        out = subprocess.check_output(
            ["calkit", "push", "--no-git", "--no-dvc"], text=True
        )
        assert "Pushing image" not in out
        assert "already in the registry" in out
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        subprocess.run(["docker", "rmi", "-f", image], capture_output=True)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Docker daemon not available on windows-latest GHA runners",
)
def test_check_docker_env_keeps_unpushed_digests_out_of_the_lock(tmp_dir):
    with open("Dockerfile", "w") as f:
        f.write("FROM alpine:3.18\nRUN echo unpushed > /hi.txt\n")
    argv = [
        "calkit",
        "check",
        "docker-env",
        "calkit-unpushed-test",
        "-i",
        "Dockerfile",
        "-o",
        "lock.json",
        "--registry",
        "localhost:5999/unreachable",
    ]
    try:
        out = subprocess.check_output(
            argv, text=True, stderr=subprocess.STDOUT
        )
        assert "Pushing image" in out
        with open("lock.json") as f:
            lock = json.load(f)
        # Recording a digest nothing can serve would send everyone who reads
        # this lock on a failed pull
        assert lock["RepoDigests"] == []
        # And the tag the failed push left behind has to go, since it would
        # fake a registry digest on the image
        info = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "image",
                    "inspect",
                    "calkit-unpushed-test",
                    "--format",
                    "{{json .RepoDigests}}",
                ],
                text=True,
            )
        )
        assert not [d for d in info if d.startswith("localhost:5999")]
    finally:
        subprocess.run(
            ["docker", "rmi", "-f", "calkit-unpushed-test"],
            capture_output=True,
        )


def test_check_env_rejects_an_invalid_lock_property(tmp_dir):
    # A misspelled property is the user's mistake to fix, so it has to say
    # what was wrong and fail. It used to escape the local branch as a
    # traceback, and 'check envs' then reported the exit code in place of
    # the reason -- leaving a warning that said '1'.
    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "laptop": {
            "kind": "system",
            "host": socket.gethostname(),
            "lock": ["python", "os"],
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    for argv in (
        ["calkit", "check", "env", "-n", "laptop"],
        ["calkit", "check", "envs"],
    ):
        proc = subprocess.run(argv, capture_output=True, text=True)
        assert proc.returncode != 0, argv
        combined = proc.stdout + proc.stderr
        assert "Unknown system property to lock: 'python'" in combined, argv
        # The valid options are listed, since knowing the name is wrong
        # doesn't tell anyone what the right one is
        assert "python-version" in combined, argv
        assert "Traceback" not in combined, argv
    # Nothing is recorded for an environment that couldn't be locked, so a
    # stage can't depend on a half-written pin
    assert not os.path.exists(os.path.join(".calkit", "env-locks", "laptop"))


def test_check_env_checks_system_requirements(tmp_dir):
    # A system env's requirements gate the machine it names, and are
    # checked before its lock is written, so a machine that doesn't meet
    # them never has its properties recorded as what results depend on
    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "laptop": {
            "kind": "system",
            "host": socket.gethostname(),
            "requirements": [{"kind": "cpu-count", "min": 10000}],
            "lock": ["os"],
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    proc = subprocess.run(
        ["calkit", "check", "env", "-n", "laptop"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "cpu-count" in combined
    assert "Environment 'laptop'" in combined
    assert "Traceback" not in combined
    lock_fpath = os.path.join(".calkit", "env-locks", "laptop", "info.json")
    assert not os.path.exists(lock_fpath)
    # Met requirements let the check proceed to writing the lock
    ck_info["environments"]["laptop"]["requirements"] = [
        {"kind": "cpu-count", "min": 1}
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "check", "env", "-n", "laptop"])
    assert os.path.exists(lock_fpath)


def test_check_envs_preloads_env_vars(tmp_dir, monkeypatch):
    # Verify that `calkit check envs` loads .env and calkit.yaml env_vars
    # before checking environments, so env-var-gated checks see them.
    # The environment uses $CALKIT_VAR as its path so the check fails if
    # the env var isn't preloaded before check_environment is called.
    subprocess.check_call(["calkit", "init"])
    with open(".env", "w") as f:
        f.write("DOT_ENV_VAR=from_dotenv\n")
    ck_info = calkit.load_calkit_info()
    # CALKIT_VAR holds the requirements file path; it is set via env_vars so
    # check envs must preload it before the venv check can resolve $CALKIT_VAR
    ck_info["env_vars"] = {"CALKIT_VAR": "requirements.txt"}
    ck_info["environments"] = {
        "test-env": {
            "kind": "uv-venv",
            "path": "$CALKIT_VAR",
            "prefix": ".venv",
            "python": "3.13",
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    # Ensure vars are NOT already in the environment so only preloading sets them
    monkeypatch.delenv("DOT_ENV_VAR", raising=False)
    monkeypatch.delenv("CALKIT_VAR", raising=False)
    # Should succeed: check envs preloads CALKIT_VAR → path resolves to
    # requirements.txt; without preloading $CALKIT_VAR would not resolve
    subprocess.check_call(["calkit", "check", "envs"])
