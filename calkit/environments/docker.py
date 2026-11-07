"""Calkit's Docker environments: building, locking, and fetching their
images.
"""

from __future__ import annotations

import json
import os
import posixpath
import subprocess
import sys
from pathlib import Path

import calkit


def check_image(
    tag: str,
    fpath: str | None = None,
    lock_fpath: str | None = None,
    alt_lock_fpaths: list[str] = [],
    alt_lock_fpaths_delete: list[str] = [],
    platform: str | None = None,
    user: str | None = None,
    wdir: str | None = None,
    deps: list[str] = [],
    env_vars: list[str] = [],
    ports: list[str] = [],
    gpus: str | None = None,
    args: list[str] = [],
    build_platforms: list[str] = [],
    registry: str | None = None,
    lock_archs: list[str] = [],
    quiet: bool = False,
    rebuild: bool = False,
    env_name: str | None = None,
) -> None:
    """Check that an image matches its lock, getting or building it if
    not, and lock it.

    ``env_name`` is the environment's name in calkit.yaml, if it has one,
    so errors can suggest commands that use it.
    """
    import typer

    from calkit import docker as ck_docker
    from calkit.cli import raise_error, warn
    from calkit.core import get_md5, is_tty
    from calkit.environments import get_docker_arch

    if fpath is None and lock_fpath is None:
        raise_error(
            "Lock file output path must be provided if input Dockerfile is not"
        )
    try:
        ck_docker.ensure_ready(interactive=is_tty())
    except ck_docker.DockerNotReadyError as e:
        raise_error(str(e))
    outfile = open(os.devnull, "w") if quiet else None
    if fpath is not None:
        typer.echo(f"Reading Dockerfile from {fpath}", file=outfile)
        dockerfile_md5 = get_md5(fpath)
    else:
        dockerfile_md5 = None
    if lock_fpath is None and fpath is not None:
        lock_fpath = fpath + "-lock.json"
    else:
        lock_fpath = str(lock_fpath)
    # Compute MD5s of any dependencies
    deps_md5s = {}
    for dep in deps:
        deps_md5s[dep] = get_md5(dep, exclude_files=[lock_fpath])

    def read_lock(path: str) -> dict | None:
        # A lock that can't be read is treated as one that isn't there:
        # rebuilding is always an option, so there's no reason to fail
        try:
            with open(path) as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        # Handle legacy lock files that are lists
        if isinstance(loaded, list):
            loaded = loaded[0] if loaded else None
        return loaded if isinstance(loaded, dict) else None

    # Read the lock file, falling back to legacy paths and then to other
    # architectures, which still identify the image well enough to pull it
    lock = None
    lock_is_current_arch = False
    legacy_lock_fpath = None
    if os.path.isfile(lock_fpath):
        typer.echo(f"Reading lock file: {lock_fpath}", file=outfile)
        lock = read_lock(lock_fpath)
        lock_is_current_arch = lock is not None
    else:
        typer.echo(f"Lock file ({lock_fpath}) does not exist", file=outfile)
        for alt_lock_fpath in alt_lock_fpaths_delete:
            if os.path.isfile(alt_lock_fpath):
                typer.echo(
                    f"Reading alternative lock file: {alt_lock_fpath}",
                    file=outfile,
                )
                lock = read_lock(alt_lock_fpath)
                # A legacy lock was written before locks were kept per
                # architecture, by the machine that checked the
                # environment, so it describes this one. Taking it for
                # another architecture's would skip checking the local image
                # against it, and an image left under this tag by something
                # else would be locked in as this environment's
                lock_is_current_arch = lock is not None
                # Removed once its replacement is written, so a failed
                # check doesn't leave the environment with no lock at all
                legacy_lock_fpath = alt_lock_fpath
                break
        if lock is None:
            for alt_lock_fpath in alt_lock_fpaths:
                if os.path.isfile(alt_lock_fpath):
                    typer.echo(
                        f"Reading alternative lock file: {alt_lock_fpath}",
                        file=outfile,
                    )
                    lock = read_lock(alt_lock_fpath)
                    if lock is not None:
                        break
    # An environment named after an existing image has that name as its spec
    spec_image = tag if fpath is None else None
    # A lock that doesn't describe the current spec is stale, not merely
    # out-of-date with the local image: the image it identifies was built
    # from a different Dockerfile or dependencies, or is a different image
    # altogether, so it must not be pulled in place of the one asked for
    if lock is not None and not ck_docker.lock_matches_spec(
        lock,
        dockerfile_md5=dockerfile_md5,
        deps_md5s=deps_md5s,
        image=spec_image,
    ):
        typer.echo(
            "Lock file does not match the current environment", file=outfile
        )
        lock = None
        lock_is_current_arch = False
    # Without a Dockerfile, rebuilding means pulling the image again
    if rebuild:
        lock = None
        lock_is_current_arch = False
    # A lock written before the image was recorded still pins it, and adding
    # it would rerun every stage in the environment, so it's left out until
    # the environment is relocked
    record_image = spec_image if lock is None or "Image" in lock else None
    # Work out where this image lives in a registry, so it can be pulled
    # instead of rebuilt, and pushed after being built. Only an image built
    # from a Dockerfile goes to the project's registry; one named directly
    # already lives somewhere it can be pulled back from.
    remote_ref = None
    registry_prefix = ck_docker.resolve_registry_prefix(
        {"registry": registry, "path": fpath}
    )
    if registry_prefix is None and ck_docker.registry_is_auto(registry):
        warn(
            "Could not work out a registry for this project; name one "
            "explicitly, e.g., 'ghcr.io/someone/some-project', or set "
            "a GitHub remote"
        )
    remote_repo = None
    if registry_prefix is not None and fpath is not None:
        remote_ref = ck_docker.get_remote_image_ref(tag, registry_prefix)
        remote_repo = ck_docker.get_repo_from_ref(remote_ref)
    # Where a digest the lock records can be pulled from, since the lock
    # names the digest alone: the project's registry for an image we build,
    # or the image's own repo for one named directly. Working this out from
    # the environment definition rather than the lock is what stops a digest
    # left over from a different image resolving to anything
    digest_source_ref = remote_ref if remote_ref is not None else tag
    typer.echo(f"Checking for existing image with tag {tag}", file=outfile)
    identity = ck_docker.inspect_image_for_lock(tag)
    if identity is None:
        typer.echo(f"No image with tag {tag} found locally", file=outfile)
    # Only a lock for this architecture can say whether the image here is
    # the one it describes: another architecture's layers never match, so
    # its lock is taken as an instruction to fetch the image it names rather
    # than as a blessing for whatever happens to carry this tag
    up_to_date = (
        identity is not None
        and lock is not None
        and lock_is_current_arch
        and ck_docker.lock_matches_image(lock, identity)
    )

    digest_refs = (
        ck_docker.get_lock_digest_refs(lock, digest_source_ref)
        if lock is not None
        else []
    )
    # A lock that names a digest somewhere it can be pulled from pins the
    # environment to that image, like a package lock pins versions, so it
    # isn't replaced without being asked. One for a Dockerfile with no
    # registry names nothing anyone could pull, so a rebuild is all there is.
    pinned = bool(digest_refs) and (fpath is None or remote_ref is not None)
    pulled_from_registry = False
    already_pushed = False
    built = False
    if not up_to_date:
        obtained = False
        # Prefer pulling the exact image the lock identifies, since a rebuild
        # can't reproduce it, and would silently pick up whatever its
        # undeclared upstream dependencies have become
        if lock is not None:
            for digest_ref in digest_refs:
                typer.echo(f"Pulling image by digest: {digest_ref}", err=True)
                # A private image needs credentials we may be able to get,
                # but only a registry that refused us is worth logging in to
                if not ck_docker.pull_image_with_login(
                    digest_ref, platform=platform
                ):
                    warn(f"Failed to pull image by digest: {digest_ref}")
                    continue
                if not ck_docker.tag_image(digest_ref, tag):
                    warn(f"Failed to tag pulled image as {tag}")
                    continue
                identity = ck_docker.inspect_image_for_lock(tag)
                if identity is None:
                    continue
                if lock_is_current_arch and not ck_docker.lock_matches_image(
                    lock, identity
                ):
                    warn(
                        f"Image pulled from {digest_ref} does not match the "
                        "lock file"
                    )
                    continue
                obtained = True
                pulled_from_registry = (
                    remote_repo is not None
                    and digest_ref.split("@", 1)[0] == remote_repo
                )
                break
        # A lock from another architecture named an image we've now tried
        # to pull. Failing that, an image already here was built from this
        # same spec, so it stands rather than being rebuilt for a lock that
        # was never able to describe it
        if (
            not obtained
            and identity is not None
            and lock is not None
            and not lock_is_current_arch
        ):
            obtained = True
        # Fall back to an image archived in a release, since a registry makes
        # no promise to keep an image forever, and rebuilding can't reproduce
        # one whose upstream dependencies have moved on
        if not obtained and lock is not None and lock_is_current_arch:
            layers = (lock.get("RootFS") or {}).get("Layers") or []
            archived = calkit.releases.find_archived_docker_image(layers)
            if archived is not None:
                release_name, image_id, entry = archived
                typer.echo(
                    f"Fetching image archived in release '{release_name}'",
                    err=True,
                )
                if calkit.releases.fetch_archived_docker_image(
                    release_name, entry
                ) and ck_docker.tag_image(image_id, tag):
                    identity = ck_docker.inspect_image_for_lock(tag)
                    if identity is not None and ck_docker.lock_matches_image(
                        lock, identity
                    ):
                        obtained = True
                    else:
                        warn(
                            f"Image archived in release '{release_name}' does "
                            "not match the lock file"
                        )
                else:
                    warn(
                        "Failed to fetch image archived in release "
                        f"'{release_name}'"
                    )
        # Rebuilding or pulling the tag would swap in a different image and
        # rewrite the lock, which only happens when asked for
        if not obtained and pinned:
            relock = (
                f"'calkit update env -n {env_name} --lock'"
                if env_name
                else "this command with --rebuild"
            )
            causes = (
                "if it's in a private package, log in or make it public; if "
                "it was never pushed, push it from the machine that built it "
                "with 'calkit push docker'"
                if fpath is not None
                else "if it's private, log in to its registry"
            )
            raise_error(
                f"Failed to get the image this environment is locked to "
                f"({digest_refs[0]}), so it was left alone rather than "
                f"replaced with a different one; {causes}; or, to replace "
                f"the image and its lock, run {relock}"
            )
        if not obtained and fpath is not None:
            dockerfile_dir, dockerfile_name = os.path.split(fpath)
            build_cwd = dockerfile_dir if dockerfile_dir else None
            # A multi-platform image can't live in the local image store, so
            # it's built straight into the registry and pulled back for the
            # platform we're on
            multi_platform = len(build_platforms) > 1
            if multi_platform and remote_ref is None:
                raise_error(
                    "Building for multiple platforms requires a registry; "
                    "set 'registry' on this environment"
                )
            if multi_platform:
                assert remote_ref is not None
                cmd = [
                    "docker",
                    "buildx",
                    "build",
                    "--platform",
                    ",".join(build_platforms),
                    "-t",
                    remote_ref,
                    "--push",
                    "-f",
                    dockerfile_name,
                ]
                if rebuild:
                    cmd += ["--no-cache", "--pull"]
                cmd.append(".")
            else:
                cmd = ["docker", "build", "-t", tag, "-f", dockerfile_name]
                if rebuild:
                    cmd += ["--no-cache", "--pull"]
                build_platform = (
                    build_platforms[0] if build_platforms else platform
                )
                if build_platform is not None:
                    cmd += ["--platform", build_platform]
                cmd.append(".")
            try:
                subprocess.check_output(cmd, cwd=build_cwd)
            except subprocess.CalledProcessError:
                raise_error(
                    f"Failed to build Docker image with tag {tag} from {fpath}"
                )
            built = True
            if multi_platform:
                assert remote_ref is not None
                already_pushed = True
                if not ck_docker.pull_image_with_login(
                    remote_ref, platform=platform
                ) or not ck_docker.tag_image(remote_ref, tag):
                    raise_error(
                        f"Failed to pull image back from {remote_ref} after "
                        "building it"
                    )
        elif not obtained:
            typer.echo(f"Pulling image: {tag}", err=True)
            if not ck_docker.pull_image_with_login(tag, platform=platform):
                raise_error(f"Failed to pull image: {tag}")
    identity = ck_docker.inspect_image_for_lock(tag)
    if identity is None:
        raise_error(f"Failed to inspect image with tag {tag}")
    assert identity is not None
    # Checking an environment doesn't publish it: that's what 'calkit push'
    # is for. A multi-platform build is the exception, since buildx has
    # nowhere but the registry to put the image it assembles.
    pushed = already_pushed
    # A digest already recorded for the project's own registry stands, since
    # it says the image got there on some earlier push or pull. The image's
    # own digests can't answer this: tagging one for a registry gives it a
    # digest under that repo whether or not anything was ever sent.
    lock_remote_digests = []
    if lock is not None and remote_repo is not None:
        lock_remote_digests = [
            d
            for d in (lock.get("RepoDigests") or [])
            # A digest recorded bare is one this project put in its own
            # registry, since that's the only kind it records; locks written
            # before digests were stored bare name their repo outright
            if "@" not in d or d.split("@", 1)[0] == remote_repo
        ]
    # A digest belongs in the lock whenever there's a registry to pull it
    # from. An image store that keeps a manifest gives a build the digest it
    # will have once pushed, since a manifest is content-addressed, so it
    # can be recorded before the push and a clone pulls the image as soon as
    # anyone sends it. One that doesn't has to be pushed to learn it.
    if remote_ref is not None:
        if pushed or pulled_from_registry:
            remote_digests = ck_docker.keep_only_repo_digests(
                identity, remote_ref
            )["RepoDigests"]
        elif lock is not None and ck_docker.lock_matches_image(lock, identity):
            # Still the same image an earlier run verified, so what it
            # recorded stands and the lock doesn't churn. A lock written
            # before digests were taken from the build recorded none, and
            # keeping that would leave the gap in place for as long as the
            # image goes unrebuilt, so the image's own digest fills it
            remote_digests = (
                lock_remote_digests or ck_docker.get_content_digests(identity)
            )
        else:
            remote_digests = ck_docker.get_content_digests(identity)
        # An image store that keeps no manifest gives a build no digest of
        # its own: a manifest names the compressed layers, and nothing
        # compresses them until a push. Checking doesn't publish, so the
        # lock records none, and the containerd image store is the way out
        if not remote_digests and fpath is not None:
            warn(
                "This Docker engine only gives an image a digest when it's "
                "pushed, so this environment's lock file will record none, "
                "and anyone else who uses this project will rebuild the "
                "image rather than pull it; switch Docker to the containerd "
                "image store so a build gets the digest it will have in the "
                f"registry: {ck_docker.CONTAINERD_STORE_DOCS_URL}"
            )
        identity = dict(identity, RepoDigests=remote_digests)
    elif fpath is None:
        # An environment named after someone else's image is pullable by
        # whatever digests it arrived with
        identity = ck_docker.keep_only_repo_digests(identity, tag)
    else:
        # An image built where the store assigns no digest, with no registry
        # to send it to, leaves nothing in the lock that anyone could pull
        if built and not ck_docker.get_content_digests(identity):
            warn(
                "This Docker engine only assigns an image a digest when "
                "it's pushed, so this environment's lock file will record "
                "none, and anyone else who uses this project will rebuild "
                "the image rather than pull it; set 'registry' on the "
                "environment and switch Docker to the containerd image store "
                f"({ck_docker.CONTAINERD_STORE_DOCS_URL}) to record one"
            )
        identity = ck_docker.keep_only_repo_digests(identity, None)
    # Read the other platforms from the exact image this one locked, rather
    # than from the tag. A tag moves, and asking it again would lock the
    # other platforms to whatever it points at now, leaving one set of lock
    # files describing two different builds. Going by digest gives every
    # platform the same image and its own layers within it.
    remote_source_ref = None
    if identity["RepoDigests"]:
        remote_source_ref = ck_docker.get_lock_digest_refs(
            identity, digest_source_ref
        )[0]
    elif fpath is None:
        remote_source_ref = tag
    # Run configuration doesn't affect which image we need, but does affect
    # how stages run in it, so it belongs in the lock to invalidate them
    run_config: dict = {}
    if platform is not None:
        run_config["Platform"] = platform
    if wdir is not None:
        run_config["WorkDir"] = wdir
    if user is not None:
        run_config["User"] = user
    if env_vars:
        run_config["EnvVars"] = env_vars
    if ports:
        run_config["Ports"] = ports
    if gpus:
        run_config["GPUs"] = gpus
    if args:
        run_config["Args"] = args

    def write_lock(arch: str, arch_identity: dict) -> None:
        if arch == current_arch:
            arch_lock_fpath = lock_fpath
        else:
            arch_lock_fpath = os.path.join(lock_dir, arch + ".json")
        arch_lock = ck_docker.build_lock(
            identity=arch_identity,
            dockerfile_md5=dockerfile_md5,
            deps_md5s=deps_md5s,
            run_config=run_config,
            image=record_image,
        )
        # newline="\n" so the file is byte-identical on every platform,
        # rather than a Windows checkout flipping it to CRLF.
        with open(arch_lock_fpath, "w", newline="\n") as f:
            json.dump(arch_lock, f, indent=4)

    current_arch = get_docker_arch()
    lock_dir = os.path.dirname(lock_fpath)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    write_lock(current_arch, identity)
    if legacy_lock_fpath is not None:
        os.remove(legacy_lock_fpath)
    # Lock the platforms this machine can't run, so that moving the project
    # to one of them doesn't invalidate every stage in the environment. An
    # existing lock that still describes this spec is reused rather than
    # re-read from the registry, which keeps checks working offline
    stale_archs = []
    contradicted = False
    for arch in [a for a in lock_archs if a != current_arch]:
        arch_lock_fpath = os.path.join(lock_dir, arch + ".json")
        existing = (
            read_lock(arch_lock_fpath)
            if os.path.isfile(arch_lock_fpath)
            else None
        )
        if (
            existing is not None
            and ck_docker.lock_matches_spec(
                existing,
                dockerfile_md5=dockerfile_md5,
                deps_md5s=deps_md5s,
                image=spec_image,
            )
            and ck_docker.get_content_digests(existing)
            == ck_docker.get_content_digests(identity)
        ):
            write_lock(arch, existing)
        else:
            # A lock naming a different image than this platform's describes
            # another build entirely, and leaving one set of lock files
            # saying two things is worse than the round-trip to settle it
            contradicted = contradicted or existing is not None
            stale_archs.append(arch)
    # Asking the registry which platforms it serves costs a round-trip, and
    # the answer only changes when the image does. An image that's still the
    # one the lock describes was already asked about on the run that locked
    # it, so a platform the registry doesn't publish isn't asked about again
    # on every check from then on. Nothing is removed either, since a lock
    # can only be judged stale against an answer we actually have.
    if (
        stale_archs
        and remote_source_ref is not None
        and (not up_to_date or contradicted)
    ):
        typer.echo(
            f"Reading platforms available for {remote_source_ref}",
            file=outfile,
        )
        remote_locks = ck_docker.get_remote_image_platform_locks(
            remote_source_ref
        )
        if remote_locks is None:
            # Being unable to ask says nothing about what the registry
            # serves, and a lock can only be judged stale against an answer
            # we actually have, so the other platforms' locks stand
            typer.echo(
                f"Could not read platforms available for {remote_source_ref}",
                file=outfile,
            )
        else:
            for arch in stale_archs:
                arch_lock_fpath = os.path.join(lock_dir, arch + ".json")
                if arch in remote_locks:
                    write_lock(arch, remote_locks[arch])
                elif os.path.isfile(arch_lock_fpath):
                    # A lock left behind for a platform this image no longer
                    # has would describe an image built from something else
                    os.remove(arch_lock_fpath)


def get_image_name(env_name: str, env: dict, wdir: str | None = None) -> str:
    """Name the image an environment runs in.

    An environment that builds from a Dockerfile doesn't have to be told
    what to call its image: the project and environment it belongs to name
    it unambiguously, by the same convention its Jupyter kernel is named
    by. One defined purely by an image has to name it, since it's someone
    else's.

    A project with nothing to be named after, i.e., no ``owner`` or
    ``name`` in ``calkit.yaml`` and no Git remote to read them from, can't
    name its images either. The directory a project happens to sit in is
    not a name---moving or renaming it would rename the image, and every
    image built by every project called ``analysis`` would collide---so
    this is for the project to say rather than for Calkit to guess.

    Raises ValueError, saying why, if there's no name.
    """
    image: str | None = env.get("image")
    if image:
        return image
    if not env.get("path"):
        raise ValueError(
            f"Environment '{env_name}' must define an image, since it has "
            "no Dockerfile to build one from"
        )
    project: str | None
    try:
        project = calkit.detect_project_name(wdir=wdir)
    except ValueError:
        # A project that isn't published anywhere yet still names itself if
        # calkit.yaml says what it's called
        project = calkit.load_calkit_info(wdir=wdir).get("name")
        if not project:
            raise ValueError(
                "Cannot work out what to call the image for environment "
                f"'{env_name}': set 'image' on it, or set 'owner' and "
                "'name' in calkit.yaml"
            )
    # Repository names must be lowercase, unlike tags
    return f"{project}.{env_name}".lower()


def get_lock_fpaths(
    env_name: str, wdir: str | None = None, as_posix: bool = True
) -> list[str]:
    """List every lock an environment can have: one per architecture, then
    the legacy one from before locks were per architecture.
    """
    from calkit.environments import DOCKER_ARCHS, get_env_lock_dir

    env_lock_dir = get_env_lock_dir(wdir=wdir)
    fpaths = [
        os.path.join(env_lock_dir, env_name, arch + ".json")
        for arch in DOCKER_ARCHS
    ] + [os.path.join(env_lock_dir, env_name + ".json")]
    if as_posix:
        fpaths = [Path(p).as_posix() for p in fpaths]
    return fpaths


def check(
    env_name: str, env: dict, rebuild: bool = False, verbose: bool = False
) -> None:
    """Check an environment defined in calkit.yaml, getting or building its
    image and locking it.
    """
    from calkit import docker as ck_docker
    from calkit.cli import raise_error
    from calkit.environments import get_env_input_paths, get_env_lock_fpath

    try:
        image = get_image_name(env_name, env)
    except ValueError as e:
        raise_error(str(e))
    *alt_lock_fpaths, legacy_lock_fpath = get_lock_fpaths(
        env_name, as_posix=False
    )
    check_image(
        tag=image,
        fpath=env.get("path"),
        lock_fpath=get_env_lock_fpath(
            env=env, env_name=env_name, as_posix=False
        ),
        alt_lock_fpaths_delete=[legacy_lock_fpath],
        alt_lock_fpaths=alt_lock_fpaths,
        platform=env.get("platform"),
        deps=get_env_input_paths(env, env_name),
        env_vars=env.get("env_vars", []),
        ports=env.get("ports", []),
        gpus=env.get("gpus"),
        user=env.get("user"),
        wdir=env.get("wdir"),
        args=env.get("args", []),
        build_platforms=env.get("build_platforms", []),
        registry=env.get("registry"),
        lock_archs=ck_docker.get_lock_archs(env),
        quiet=not verbose,
        rebuild=rebuild,
        env_name=env_name,
    )


def run(
    env_name: str,
    env: dict,
    cmd: list[str],
    wdir: str | None = None,
    env_vars: dict[str, str] | None = None,
    verbose: bool = False,
) -> None:
    """Run a command in an environment's container, with the project
    mounted at its working directory.

    ``wdir`` is relative to the project, and ``env_vars`` are passed into
    the container on top of the environment's and project's own.
    """
    import typer

    from calkit import docker as ck_docker
    from calkit.cli import raise_error, warn
    from calkit.cli.main.core import _to_shell_cmd

    command_mode = env.get("command_mode", "shell")
    if command_mode not in ["shell", "entrypoint"]:
        raise_error(
            "Invalid Docker environment 'command_mode': "
            f"{command_mode}; Use 'shell' or 'entrypoint'"
        )
    try:
        image = get_image_name(env_name, env)
    except ValueError as e:
        raise_error(str(e))
    docker_wdir = env.get("wdir", "/work")
    docker_wdir_mount = docker_wdir
    if wdir is not None:
        docker_wdir = posixpath.join(docker_wdir, wdir)
    shell = env.get("shell", "sh")
    platform = env.get("platform")
    docker_cmd = [
        "docker",
        "run",
    ]
    if platform:
        docker_cmd += ["--platform", platform]
    container_env_vars = dict(env.get("env_vars", {}))
    if "env-vars" in env:
        warn("The 'env-vars' key is deprecated; use 'env_vars' instead.")
        container_env_vars.update(env["env-vars"])
    # Add project-level env vars (non-secret)
    container_env_vars.update(calkit.load_calkit_info().get("env_vars", {}))
    # Also add any project-level environmental variable dependencies
    project_env_vars = calkit.get_env_var_dep_names()
    if project_env_vars:
        container_env_vars.update({k: f"${k}" for k in project_env_vars})
    if container_env_vars:
        for key, value in container_env_vars.items():
            if isinstance(value, str):
                value = os.path.expandvars(value)
            docker_cmd += ["-e", f"{key}={value}"]
    # A container inherits nothing from here, so what --env-var asked
    # for has to be handed to it
    for key, value in (env_vars or {}).items():
        docker_cmd += ["-e", f"{key}={value}"]
    if (gpus := env.get("gpus")) is not None:
        docker_cmd += ["--gpus", gpus]
    if ports := env.get("ports"):
        for port in ports:
            docker_cmd += ["-p", port]
    docker_user = env.get("user")
    if docker_user is None:
        try:
            uid = os.getuid()
            gid = os.getgid()
            docker_user = f"{uid}:{gid}"
        except AttributeError:
            # We're probably on Windows, so there is no UID to map
            pass
    if docker_user is not None:
        docker_cmd += ["--user", docker_user]
    docker_cmd += env.get("args", [])
    docker_cmd += [
        # A pipeline stage is nobody's terminal session: asking for a
        # TTY there puts the user's terminal into raw mode for the
        # duration, and the container's own line discipline stops
        # translating newlines, so everything the stage prints
        # staircases down the screen. DVC sets DVC_STAGE for the
        # commands it runs, which is how a stage is told apart from
        # someone running 'calkit xenv' themselves
        "-it" if sys.stdin.isatty() and not os.getenv("DVC_STAGE") else "-i",
        "--rm",
        "-w",
        docker_wdir,
        "-v",
        f"{os.getcwd()}:{docker_wdir_mount}",
        image,
    ]
    if command_mode == "shell":
        shell_cmd = _to_shell_cmd(cmd)
        docker_cmd += [shell, "-c", shell_cmd]
    else:
        if not cmd:
            raise_error(
                "No command provided for Docker environment in "
                "'entrypoint' command mode"
            )
        docker_cmd += cmd
    if verbose:
        typer.echo(f"Running command: {docker_cmd}")
    try:
        subprocess.check_call(docker_cmd, cwd=wdir)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        # Docker exits 125 when it couldn't run the container at all,
        # which is most often because Docker itself isn't running
        if isinstance(e, FileNotFoundError) or e.returncode == 125:
            try:
                ck_docker.ensure_ready()
            except ck_docker.DockerNotReadyError as ready_error:
                raise_error(str(ready_error))
        returncode = getattr(e, "returncode", None)
        raise_error(
            "Failed to run in Docker environment: command exited with "
            f"status {returncode}"
        )
