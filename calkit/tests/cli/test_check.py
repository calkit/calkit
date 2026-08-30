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
import calkit.environments


def engine_records_build_digests() -> bool:
    # The containerd image store writes a manifest when an image is built,
    # so the image carries the digest it will have in a registry before it
    # is pushed anywhere. The classic store writes none: a manifest names
    # the compressed layers, and nothing compresses them until a push, so a
    # digest only exists once the image has been sent somewhere.
    try:
        out = subprocess.check_output(
            ["docker", "info", "--format", "{{json .DriverStatus}}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return "io.containerd.snapshotter" in out


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
    out = subprocess.check_output(
        [
            "calkit",
            "check",
            "docker-env",
            "python-3.9-slim",
            "-i",
            "Dockerfile",
            "-o",
            "Dockerfile-lock.json",
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )
    with open("Dockerfile-lock.json") as f:
        lock = json.load(f)
    # What an image is called is in calkit.yaml, not in the lock, so
    # renaming it doesn't rerun every stage in the environment
    assert "RepoTags" not in lock
    # An image built here and never pushed anywhere has a digest no registry
    # can serve, which would send anyone reading the lock on a failed pull
    assert lock["RepoDigests"] == []
    # Where the image store gives a build no digest at all, there is nothing
    # to record even once a registry is configured without a push, so say so
    # while the build that prompted it is still on screen
    if not engine_records_build_digests():
        assert "set 'registry' on the environment" in out
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
    with open("Dockerfile-lock.json", "rb") as f:
        renamed_lock_bytes = f.read()
    # Renaming the image leaves the lock alone: it describes the same
    # content, and a rename that reran every stage would be reporting a
    # change to software that didn't change
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
    with open("Dockerfile-lock.json", "rb") as f:
        assert f.read() == renamed_lock_bytes
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
    out = subprocess.check_output(argv, text=True)
    # The other platforms are read from the exact image this one locked, not
    # from the tag, which can move onto a different build between checks and
    # leave one set of lock files describing two of them
    assert "Reading platforms available for alpine@sha256:" in out
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
def test_check_docker_env_migrates_a_legacy_lock(tmp_dir):
    image = "calkit-legacy-lock-test"
    subprocess.check_call(["calkit", "init"])
    with open("Dockerfile", "w") as f:
        f.write("FROM alpine:3.18\nRUN echo legacy > /hi.txt\n")
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "main": {"kind": "docker", "path": "Dockerfile", "image": image}
    }
    calkit.save_calkit_info(ck_info)
    check_argv = ["calkit", "check", "environment", "-n", "main"]
    arch = calkit.environments.get_docker_arch()
    lock_fpath = f".calkit/env-locks/main/{arch}.json"
    legacy_lock_fpath = ".calkit/env-locks/main.json"
    try:
        subprocess.check_call(check_argv)
        with open(lock_fpath) as f:
            built_lock = json.load(f)
        # A project locked before locks were kept per architecture has a
        # single lock file named after the environment, written by the
        # machine that checked it, so it describes this architecture
        os.replace(lock_fpath, legacy_lock_fpath)
        # Something else leaving an image under this tag must not be taken
        # for the one the lock describes and written into the migrated lock,
        # which is what taking a legacy lock for another architecture's did:
        # its image is never checked against the lock, since it isn't
        # expected to be here. It's built rather than tagged from an
        # existing image, since another test running alongside this one is
        # free to delete whatever that image was
        with open("Other.dockerfile", "w") as f:
            f.write("FROM alpine:3.18\nRUN echo something-else > /hi.txt\n")
        subprocess.check_call(
            ["docker", "build", "-t", image, "-f", "Other.dockerfile", "."]
        )
        subprocess.check_call(check_argv)
        assert not os.path.isfile(legacy_lock_fpath)
        with open(lock_fpath) as f:
            migrated = json.load(f)
        assert migrated["RootFS"]["Layers"] == built_lock["RootFS"]["Layers"]
        assert migrated["DockerfileMD5"] == built_lock["DockerfileMD5"]
    finally:
        subprocess.run(["docker", "rmi", "-f", image], capture_output=True)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Docker daemon not available on windows-latest GHA runners",
)
def test_check_docker_env_pulls_from_registry_instead_of_rebuilding(tmp_dir):
    container = "calkit-test-registry"
    registry = "localhost:5678"
    subprocess.run(["docker", "rm", "-f", container], capture_output=True)
    # An image left in the daemon by an earlier run still carries a digest
    # under this registry, and a rebuild lands on it, since it has the same
    # content, which would make an image that was never sent to this
    # registry look like one that was. A '--filter reference=' doesn't match
    # an image whose only reference is a digest, which is the kind left
    # behind here, so the listing is scanned instead
    listed = subprocess.check_output(
        ["docker", "images", "-a", "--format", "{{.Repository}} {{.ID}}"],
        text=True,
    ).splitlines()
    stale = [
        line.split()[-1] for line in listed if line.startswith(f"{registry}/")
    ]
    if stale:
        subprocess.run(["docker", "rmi", "-f"] + stale, capture_output=True)
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
        image = "calkit-registry-test"
        subprocess.check_call(["calkit", "init"])
        with open("Dockerfile", "w") as f:
            f.write("FROM alpine:3.18\nRUN echo hi > /hi.txt\n")
        ck_info = calkit.load_calkit_info()
        ck_info["environments"] = {
            "main": {
                "kind": "docker",
                "path": "Dockerfile",
                "image": image,
                "registry": f"{registry}/proj",
            }
        }
        calkit.save_calkit_info(ck_info)
        check_argv = ["calkit", "check", "environment", "-n", "main"]
        arch = calkit.environments.get_docker_arch()
        lock_fpath = f".calkit/env-locks/main/{arch}.json"
        # Checking builds the image and records the digest it will have in
        # the registry. Where the image store keeps a manifest that digest
        # is the build's own, and publishing is left to 'calkit push';
        # where it doesn't, only a push can say what the digest is, so
        # checking sends the image rather than leave the lock naming
        # nothing to pull
        digests_at_build = engine_records_build_digests()
        out = subprocess.check_output(check_argv, text=True)
        if digests_at_build:
            assert "Pushing image" not in out
        else:
            assert "Pushing image" in out
        with open(lock_fpath, "rb") as f:
            built_lock_bytes = f.read()
        built_lock = json.loads(built_lock_bytes)
        assert len(built_lock["RepoDigests"]) == 1
        assert built_lock["RepoDigests"][0].startswith("sha256:")
        # An image built before a registry was configured must reach it
        # without a rebuild, or an existing project could only publish what
        # it already has by throwing it away first
        out = subprocess.check_output(
            ["calkit", "push", "--no-git", "--no-dvc"], text=True
        )
        if digests_at_build:
            assert "Pushing image for 'main'" in out
        else:
            # Checking already sent it, and pushing asks the registry rather
            # than sending it a second time
            assert "already in the registry" in out
        assert "exporting layers" not in out
        with open(lock_fpath) as f:
            lock = json.load(f)
        # Pushing sends exactly the digest the build already recorded, so
        # the lock is left alone rather than rewritten, and no stage reruns
        # for having published an image that didn't change
        assert lock["RepoDigests"] == built_lock["RepoDigests"]
        with open(lock_fpath, "rb") as f:
            assert f.read() == built_lock_bytes
        with open(lock_fpath, "rb") as f:
            lock_bytes = f.read()
        subprocess.check_call(
            [
                "docker",
                "rmi",
                "-f",
                image,
                f"{registry}/proj/{image}:latest",
            ]
        )
        out = subprocess.check_output(check_argv, text=True)
        assert "Pulling image by digest" in out
        assert "Pushing image" not in out
        # Coming back from the registry has to leave the lock exactly as it
        # was, or every stage in the environment reruns for nothing
        with open(lock_fpath, "rb") as f:
            assert f.read() == lock_bytes
        # Checking an image that hasn't changed must not go back to the
        # registry to ask which platforms it has. The answer can't have
        # changed, and asking put a network round-trip in front of every
        # check for any project whose image isn't published for both
        out = subprocess.check_output(check_argv, text=True)
        assert "Reading platforms available" not in out
        with open(lock_fpath, "rb") as f:
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
def test_push_does_not_reach_a_registry_with_nothing_to_send(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    # An environment with no registry is kept local, and one named after
    # someone else's image already lives where it can be pulled from, so
    # neither is anything to publish
    ck_info["environments"] = {
        "local": {
            "kind": "docker",
            "path": "Dockerfile",
            "image": "calkit-nothing-to-push",
        },
        "tex": {"kind": "docker", "image": "alpine:3.18"},
    }
    calkit.save_calkit_info(ck_info)
    out = subprocess.check_output(["calkit", "push", "docker"], text=True)
    assert "No Docker environments are set up to be pushed" in out
    assert "Pushing image" not in out
    # An environment that is set up, but whose image was never built here,
    # is nothing this machine can publish either. Reaching an unreachable
    # registry would mean a round-trip, and credentials asked for or
    # replaced, for a push that was never going to happen
    ck_info["environments"]["local"]["registry"] = "localhost:5999/nope"
    calkit.save_calkit_info(ck_info)
    result = subprocess.run(
        ["calkit", "push", "docker"], capture_output=True, text=True
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "No local image" in output
    assert "Pushing image" not in output
    assert "localhost:5999" not in output
    # Pushing everything doesn't nag about an image nobody asked to send
    result = subprocess.run(
        ["calkit", "push", "--no-git", "--no-dvc"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "No local image" not in result.stdout + result.stderr


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Docker daemon not available on windows-latest GHA runners",
)
def test_check_docker_env_keeps_other_arch_locks_it_cannot_ask_about(tmp_dir):
    image = "calkit-unreachable-registry-test"
    subprocess.check_call(["calkit", "init"])
    with open("Dockerfile", "w") as f:
        f.write("FROM alpine:3.18\nRUN echo unreachable > /hi.txt\n")
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "main": {
            "kind": "docker",
            "path": "Dockerfile",
            "image": image,
            "registry": "localhost:5999/unreachable",
        }
    }
    calkit.save_calkit_info(ck_info)
    arch = calkit.environments.get_docker_arch()
    other_arch = "amd64" if arch == "arm64" else "arm64"
    other_lock_fpath = f".calkit/env-locks/main/{other_arch}.json"
    try:
        subprocess.check_output(
            ["calkit", "check", "environment", "-n", "main"],
            text=True,
            stderr=subprocess.STDOUT,
        )
        # A lock for a platform this machine can't run, describing an image
        # the registry can't be asked about
        os.makedirs(os.path.dirname(other_lock_fpath), exist_ok=True)
        with open(other_lock_fpath, "w") as f:
            json.dump(
                {
                    "RepoDigests": ["sha256:" + "0" * 64],
                    "Architecture": other_arch,
                    "Os": "linux",
                    "RootFS": {"Type": "layers", "Layers": ["sha256:nope"]},
                    "DockerfileMD5": calkit.get_md5("Dockerfile"),
                    "DepsMD5s": {},
                },
                f,
                indent=4,
            )
        with open(other_lock_fpath, "rb") as f:
            other_lock_bytes = f.read()
        # Rebuilding asks the registry which platforms it serves, and it
        # can't answer. Being unable to ask is not the registry saying the
        # platform is gone, so the lock has to survive it, or a teammate on
        # that architecture rebuilds for nothing
        with open("Dockerfile", "a") as f:
            f.write("RUN echo again > /again.txt\n")
        subprocess.check_output(
            ["calkit", "check", "environment", "-n", "main"],
            text=True,
            stderr=subprocess.STDOUT,
        )
        assert os.path.isfile(other_lock_fpath)
        with open(other_lock_fpath, "rb") as f:
            assert f.read() == other_lock_bytes
    finally:
        subprocess.run(["docker", "rmi", "-f", image], capture_output=True)


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
        # Naming a target sends only that one, so an image can go out
        # without a Git push, which is what makes it usable mid-work
        out = subprocess.check_output(["calkit", "push", "docker"], text=True)
        assert "already in the registry" in out
        assert "Pushing to Git remote" not in out
        assert "Pushing to DVC remote" not in out
        # An unknown target is a typo, not a request to push everything
        result = subprocess.run(
            ["calkit", "push", "dockre"], capture_output=True, text=True
        )
        assert result.returncode != 0
        assert "Invalid target to push" in result.stderr
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        subprocess.run(["docker", "rmi", "-f", image], capture_output=True)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Docker daemon not available on windows-latest GHA runners",
)
def test_check_docker_env_does_not_push(tmp_dir):
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
        with open("lock.json") as f:
            lock = json.load(f)
        if not engine_records_build_digests():
            # This image store gives a build no digest, so the only way to
            # learn one is to push, and the registry isn't there. The lock
            # still describes the image; it just can't say where to pull it
            # from, which is reported rather than passed off as locked
            assert "Failed to push image" in out
            assert lock["RepoDigests"] == []
            return
        # Publishing an image is 'calkit push', not something that happens
        # on the way to running a stage, so an unreachable registry is not
        # even contacted here
        assert "Pushing image" not in out
        # A manifest is content-addressed, so the digest this build has is
        # the one it will have once pushed. Recording it without contacting
        # the registry is what lets a clone pull rather than rebuild as soon
        # as anyone sends the image
        assert len(lock["RepoDigests"]) == 1
        assert lock["RepoDigests"][0].startswith("sha256:")
        # A lock written before digests were taken from the build has none,
        # and the image it describes is still the one here, so the digest
        # gets filled in rather than left missing until a rebuild
        lock["RepoDigests"] = []
        with open("lock.json", "w") as f:
            json.dump(lock, f, indent=4)
        subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT)
        with open("lock.json") as f:
            backfilled = json.load(f)
        assert backfilled["RepoDigests"][0].startswith("sha256:")
        assert backfilled["RootFS"] == lock["RootFS"]
        # And nothing should have tagged the image for the registry, since
        # that would fake a registry digest on it
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


def _project() -> None:
    """A project whose paper cites one computed value and types another."""
    subprocess.check_call(["calkit", "init"])
    with open("results.json", "w") as f:
        json.dump({"DragCoefficient": 0.42, "LiftCoefficient": 1.23}, f)
    with open("compute.py", "w") as f:
        f.write("print(1)\n")
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "py": {"kind": "uv-venv", "path": "reqs.txt", "python": "3.13"}
    }
    with open("reqs.txt", "w") as f:
        f.write("polars\n")
    # The Calkit-native way to get a value onto the page: a stage computes
    # it, a json-to-latex stage turns the results file into commands, and
    # the document refers to it by key
    ck_info["pipeline"] = {
        "stages": {
            "compute": {
                "kind": "python-script",
                "environment": "py",
                "script_path": "compute.py",
                "outputs": [{"path": "results.json", "storage": "git"}],
            },
            "results-latex": {
                "kind": "json-to-latex",
                "command_name": "result",
                "inputs": ["results.json"],
                "outputs": [{"path": "results.tex", "storage": "git"}],
            },
            "build-paper": {
                "kind": "latex",
                "environment": "py",
                "target_path": "main.tex",
            },
        }
    }
    ck_info["publications"] = [
        {"title": "My Paper", "path": "main.tex", "kind": "journal-article"}
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\input{results}\n"
            "A value read from the pipeline: \\result[DragCoefficient].\n"
            "The same value typed by hand: 0.42.\n"
            "A value with nothing behind it: 3.14.\n"
            "\\ckfigure[width=0.75\\textwidth]{f.pdf}\n"
            "\\end{document}\n"
        )
    # The check reads the compiled pipeline, which is where the commands
    # that identify a from-json stage live
    calkit.pipeline.to_dvc(ck_info=ck_info, write=True)


def test_check_repro_literals(tmp_dir):
    _project()
    result = subprocess.run(
        ["calkit", "check", "repro"],
        capture_output=True,
        text=True,
        check=True,
    )
    # 0.42 is computed by the pipeline and typed into the document anyway:
    # right today, wrong the next time that stage runs. That is the copy
    # and paste worth catching, and it counts against the project.
    assert "Values typed out rather than read from the pipeline: 1" in (
        result.stdout
    )
    # 3.14 has nothing behind it, which is worth a look but is not a
    # defect: most numbers in a paper are not results
    assert "Numbers with nothing recorded behind them: 1" in result.stdout
    assert "worth a look" in result.stdout
    # The summary stays a summary and points at the findings
    assert "3.14" not in result.stdout
    assert "0.42" not in result.stdout
    assert "calkit check repro -c" in result.stdout
    out = subprocess.check_output(
        ["calkit", "check", "repro", "-c", "retyped"], text=True
    )
    assert "0.42" in out
    assert "results.json:DragCoefficient" in out
    assert "main.tex:5" in out
    out = subprocess.check_output(
        ["calkit", "check", "repro", "-c", "numbers"], text=True
    )
    assert "3.14" in out
    assert "0.42" not in out
    # A figure width is layout, not a result, whether the macro is
    # LaTeX's or Calkit's
    assert "0.75" not in out
    result_json = subprocess.run(
        ["calkit", "check", "repro", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    parsed = json.loads(result_json.stdout)
    assert [f["value"] for f in parsed["retyped_values"]] == ["0.42"]
    assert parsed["retyped_values"][0]["source"] == (
        "results.json:DragCoefficient"
    )
    assert [f["value"] for f in parsed["unattributed_numbers"]] == ["3.14"]
    # A category with nothing behind it says so rather than printing an
    # empty table, and one that isn't a category is an error
    out = subprocess.check_output(
        ["calkit", "check", "repro", "-c", "provenance"], text=True
    )
    assert "provenance: nothing to report" in out
    bad = subprocess.run(
        ["calkit", "check", "repro", "-c", "nope"],
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0
    assert "Invalid category" in bad.stderr
    # The file a json-to-latex stage writes is full of the very numbers
    # the check looks for, and reporting them would flag the fix itself
    with open("results.tex", "w") as f:
        f.write("\\newcommand\\result[1][all]{0.42 1.23 9.99}\n")
    out = subprocess.check_output(
        ["calkit", "check", "repro", "--json"], text=True
    )
    parsed = json.loads(out)
    assert [f["value"] for f in parsed["retyped_values"]] == ["0.42"]
    assert [f["value"] for f in parsed["unattributed_numbers"]] == ["3.14"]


def test_check_questions(tmp_dir):
    import json

    subprocess.check_call(["calkit", "init"])
    os.makedirs("results")
    with open("results/findings.json", "w") as f:
        json.dump({"n_top": 8}, f)
    ck_info = calkit.load_calkit_info()
    ck_info["questions"] = [
        {
            "question": "Do the top structures use the rectifier?",
            "answer": "{n_top} of eight do.",
            "evidence": [
                {
                    "kind": "value",
                    "path": "results/findings.json",
                    "key": "n_top",
                }
            ],
        }
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(["git", "commit", "-q", "-m", "Answer"])
    out = subprocess.check_output(["calkit", "check", "questions"], text=True)
    assert "1 consistent" in out
    # Listing renders the placeholder from the results file
    out = subprocess.check_output(["calkit", "list", "questions"], text=True)
    assert "answer: 8 of eight do." in out
    out = subprocess.check_output(
        ["calkit", "list", "questions", "--raw"], text=True
    )
    assert "answer: {n_top} of eight do." in out
    # The pipeline changes the number in a later commit: the check fails,
    # status warns, JSON says stale, and the listing already shows 0
    with open("results/findings.json", "w") as f:
        json.dump({"n_top": 0}, f)
    subprocess.check_call(["git", "commit", "-q", "-am", "Re-run"])
    proc = subprocess.run(
        ["calkit", "check", "questions"], capture_output=True, text=True
    )
    assert proc.returncode == 1
    assert "n_top was 8 at" in proc.stdout
    proc = subprocess.run(
        ["calkit", "check", "questions", "--json"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["questions"][0]["status"] == "stale"
    out = subprocess.check_output(
        ["calkit", "status", "--category", "questions"], text=True
    )
    assert "Questions" in out
    assert "1 stale" in out
    # Questions are asked for rather than shown by default, in JSON too
    out = subprocess.check_output(["calkit", "status", "--json"], text=True)
    assert "questions" not in json.loads(out)
    out = subprocess.check_output(
        ["calkit", "status", "--json", "-c", "questions"], text=True
    )
    assert json.loads(out)["questions"]["questions"][0]["status"] == "stale"
    out = subprocess.check_output(["calkit", "list", "questions"], text=True)
    assert "answer: 0 of eight do." in out
    # Reviewing the answer is an edit to the question, which clears it
    ck_info = calkit.load_calkit_info()
    ck_info["questions"][0]["reviewed"] = "2026-08-29"
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["git", "commit", "-q", "-am", "Review"])
    subprocess.check_call(["calkit", "check", "questions"])
