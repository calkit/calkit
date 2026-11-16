"""Calkit's TeX Live environments: TeX installed from TeX Live's own package
archives, without Docker or a system TeX.

Each TeX Live package is downloaded once, at the revision a project's lock
pins, into a store under ``~/.calkit/texlive`` that every project shares.
An environment is a small TeX Live-shaped directory in the store, named
after a hash of the packages it holds: its programs are hard links into the
store, and its ``texmf.cnf`` points kpathsea at each package's tree in
place, so nothing under ``texmf-dist`` is copied or linked at all. Two
projects with the same lock share one environment, formats included.

Packages are pinned by locking against a fixed repository, by default the
frozen final state of a past TeX Live release, so a lock means the same
files years later.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import calkit

if TYPE_CHECKING:
    from filelock import FileLock

# Bumped when what a lock or environment holds changes meaning, so old ones
# are relocked or rebuilt rather than misread
LOCK_FORMAT_VERSION = 1
VIEW_FORMAT_VERSION = 3
# Programs a package runs, which no file it loads names, so neither TeX
# Live's database nor a document's lookups find them, e.g., biblatex's
# default backend
EXTRA_DEPENDS = {"biblatex": ["biber"]}
# Programs latexmk makes a PDF with, which no log names, since it fails to
# start them; Ghostscript's dvipdf and ps2pdf come from the system
PROGRAM_PACKAGES = {
    "xelatex": "xetex",
    "dvipdfmx": "dvipdfmx",
    "dvips": "dvips",
}
# What converting LaTeX to other formats with make4ht needs, beyond what
# the document does, which isn't locked, since a conversion isn't part of
# the pipeline
TEX4HT_PACKAGES = ["make4ht", "tex4ht", "luaxml"]
# The latest TeX Live release whose repository is frozen, so locking against
# it pins every package for good
DEFAULT_RELEASE = 2025
# The environment created for a LaTeX document that doesn't have one,
# wherever that happens: a new publication, an Overleaf import, or a stage
# whose environment is worked out from what it runs. Its release is written
# out, as 'calkit new texlive-env' does. Copied where it's used, since
# what's written into a project is the caller's to amend.
DEFAULT_ENVIRONMENT = {
    "kind": "texlive",
    "release": DEFAULT_RELEASE,
    "description": "TeX Live, installed by Calkit.",
}
# What builds run in when neither the project nor the machine has a TeX,
# locked in the store rather than a project, so packages its builds add are
# shared by every document built that way here
DEFAULT_ENV_NAME = "_texlive"
FROZEN_REPOSITORY_TEMPLATE = (
    "https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/"
    "{release}/tlnet-final"
)
# The current release's repository, which moves as packages are updated
CURRENT_REPOSITORY = "https://mirror.ctan.org/systems/texlive/tlnet"
# Locked for all of these, whichever one locking happens on, so a project
# locked on a Mac builds the same TeX on Linux and Windows
DEFAULT_LOCK_PLATFORMS = [
    "aarch64-linux",
    "universal-darwin",
    "windows",
    "x86_64-linux",
]
# Every platform TeX Live builds binaries for, which is how a package that
# only holds one platform's files is told apart from one with a dot in its
# name, e.g., 'texlive.infra'
TL_PLATFORMS = [
    "aarch64-linux",
    "amd64-freebsd",
    "amd64-netbsd",
    "armhf-linux",
    "i386-freebsd",
    "i386-linux",
    "i386-netbsd",
    "i386-solaris",
    "universal-darwin",
    "windows",
    "x86_64-cygwin",
    "x86_64-darwinlegacy",
    "x86_64-linux",
    "x86_64-linuxmusl",
    "x86_64-solaris",
]
# What every environment has, whatever the spec asks for: pdfLaTeX and
# LuaLaTeX with their formats, latexmk to drive them, and BibTeX, which
# latexmk runs whenever there's a bibliography. Without amsfonts' Type 1
# Computer Modern, pdfLaTeX falls back to bitmap fonts it can't make;
# graphicx can't load without epstopdf-pkg, nor under LuaLaTeX without
# pdftexcmds, which needs the next three; and none of those failures
# names a file to fetch.
# makeindex and latexdiff are programs, which no document names a file
# of, for indexes and for 'calkit latex diff'; about 200 kB together.
# texlive.infra brings the launcher Windows' script wrappers need, and
# tlperl the Perl latexmk runs on there; tlperl.windows is only installed
# on Windows.
BASE_PACKAGES = [
    "latex-bin",
    "latexmk",
    "bibtex",
    "amsfonts",
    "epstopdf-pkg",
    "pdftexcmds",
    "iftex",
    "infwarerr",
    "ltxcmds",
    "makeindex",
    "latexdiff",
    "texlive.infra",
    "tlperl.windows",
]
# TeX variables pointing at trees outside the environment, which would let
# whatever happens to be on the machine into a build, besides the rest of
# those in texmf.cnf
LEAKY_ENV_VARS = [
    "TEXMFCNF",
    "TEXMFHOME",
    "TEXMFVAR",
    "TEXMFCONFIG",
    "TEXMFSYSVAR",
    "TEXMFSYSCONFIG",
    "TEXMFLOCAL",
    "TEXMFDIST",
    "TEXMFROOT",
    "TEXMFAUXTREES",
]
COMPLETE_MARKER = ".calkit-complete"
# The formats builds compile with, which an environment can't do without
LATEX_FORMATS = {"pdflatex", "lualatex", "xelatex", "latex"}


def get_store_dir() -> str:
    """Return the directory holding every project's TeX Live packages.

    Absolute and normalized, since it ends up in paths TeX's tools read,
    and some, e.g., TeX4ht's xtpipes, mangle a relative or ``..`` one.
    """
    home = os.path.abspath(calkit.get_user_home())
    return os.path.join(home, ".calkit", "texlive")


def get_platform() -> str:
    """Return TeX Live's name for this machine's platform."""
    import platform

    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return "universal-darwin"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        if machine in ("x86_64", "amd64"):
            # platform.libc_ver() can't tell musl from not knowing, but
            # musl's loader is always here
            import glob

            if glob.glob("/lib/ld-musl-*.so.1"):
                return "x86_64-linuxmusl"
            return "x86_64-linux"
        if machine in ("aarch64", "arm64"):
            return "aarch64-linux"
    raise ValueError(
        f"TeX Live environments don't support this platform ({sys.platform} "
        f"{machine})"
    )


def get_package_platform(name: str) -> str | None:
    """Return the platform a package holds binaries for, if any."""
    suffix = name.rsplit(".", 1)[-1] if "." in name else None
    return suffix if suffix in TL_PLATFORMS else None


def get_spec_packages(env: dict) -> list[str]:
    """Return the packages an environment asks for, base ones included."""
    packages = env.get("packages") or []
    return list(dict.fromkeys(BASE_PACKAGES + [str(p) for p in packages]))


def get_lock_platforms(env: dict) -> list[str]:
    """Return the platforms an environment is locked for."""
    platforms = env.get("platforms") or DEFAULT_LOCK_PLATFORMS
    return sorted(set(platforms))


def calc_spec_hash(env: dict) -> str:
    """Hash what an environment's lock is resolved from."""
    spec = {
        "release": env.get("release"),
        "repository_url": env.get("repository_url"),
        "packages": sorted(get_spec_packages(env)),
        "platforms": get_lock_platforms(env),
        "lock_format": LOCK_FORMAT_VERSION,
    }
    content = json.dumps(spec, sort_keys=True)
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


def get_repository_url(env: dict) -> str:
    """Return the repository an environment is locked against.

    A release that's been frozen is fetched from TeX Live's historic
    archive. One that hasn't, i.e., the current release, can only come from
    the moving repository, so its lock holds only until packages change.
    """
    import requests

    if env.get("repository_url"):
        return str(env["repository_url"]).rstrip("/")
    release = int(env.get("release") or DEFAULT_RELEASE)
    frozen = FROZEN_REPOSITORY_TEMPLATE.format(release=release)
    resp = requests.head(
        frozen + "/tlpkg/texlive.tlpdb.xz", allow_redirects=True, timeout=30
    )
    # Only a release the archive doesn't have is the current one; any other
    # failure is reported, since falling back would lock a moving repository
    if resp.status_code == 404:
        return CURRENT_REPOSITORY
    resp.raise_for_status()
    return frozen


@functools.cache
def resolve_mirror(repository: str) -> str:
    """Pin a redirecting repository, e.g., mirror.ctan.org, to one mirror.

    Mirrors sync at different times, so a database read from one and
    packages fetched from another can disagree. Cached, so a process reads
    the database and fetches packages from the same one.
    """
    import requests

    resp = requests.head(
        repository + "/tlpkg/texlive.tlpdb.xz",
        allow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.url.removesuffix("/tlpkg/texlive.tlpdb.xz")


def parse_tlpdb(text: str) -> dict[str, dict]:
    """Parse TeX Live's package database into what locking needs.

    Each package keeps its revision, dependencies, install-time actions,
    container checksum and size, and run files, which are what a missing
    file is looked up in. Documentation and source files are left out.
    """
    packages: dict[str, dict] = {}
    for block in text.split("\n\n"):
        pkg: dict = {
            "depends": [],
            "executes": [],
            "runfiles": [],
        }
        section = None
        for line in block.splitlines():
            if line.startswith(" "):
                if section == "runfiles":
                    pkg["runfiles"].append(line.strip().split(" ")[0])
                continue
            key, _, value = line.partition(" ")
            section = None
            if key == "name":
                pkg["name"] = value
            elif key == "revision":
                pkg["revision"] = int(value)
            elif key == "depend":
                pkg["depends"].append(value)
            elif key == "execute":
                pkg["executes"].append(value)
            elif key == "containerchecksum":
                pkg["sha512"] = value
            elif key == "containersize":
                pkg["size"] = int(value)
            elif key == "runfiles":
                section = "runfiles"
        if "name" in pkg:
            packages[pkg.pop("name")] = pkg
    return packages


def load_tlpdb(repository: str, max_age_s: float = 86400) -> dict[str, dict]:
    """Load a repository's package database, cached in the store.

    A frozen repository's database never changes, so it's fetched once. A
    moving one's is fetched again once the cached copy is ``max_age_s``
    old.
    """
    import lzma
    import time

    import requests

    cache_dir = os.path.join(get_store_dir(), "tlpdb")
    key = hashlib.md5(repository.encode()).hexdigest()[:16]
    cache_fpath = os.path.join(cache_dir, key + ".json")
    if os.path.isfile(cache_fpath):
        with open(cache_fpath) as f:
            cached: dict = json.load(f)
        age = time.time() - os.path.getmtime(cache_fpath)
        if cached.get("frozen") or age < max_age_s:
            packages: dict[str, dict] = cached["packages"]
            return packages
    resp = requests.get(
        resolve_mirror(repository) + "/tlpkg/texlive.tlpdb.xz", timeout=120
    )
    resp.raise_for_status()
    packages = parse_tlpdb(lzma.decompress(resp.content).decode("utf-8"))
    config = packages.get("00texlive.config", {}).get("depends", [])
    os.makedirs(cache_dir, exist_ok=True)
    tmp_fpath = cache_fpath + f".{os.getpid()}.tmp"
    with open(tmp_fpath, "w") as f:
        json.dump(
            {
                "repository_url": repository,
                "frozen": "frozen/1" in config,
                "packages": packages,
            },
            f,
        )
    os.replace(tmp_fpath, cache_fpath)
    return packages


def get_tlpdb_release(tlpdb: dict[str, dict]) -> int | None:
    """Return the TeX Live release a package database belongs to."""
    for dep in tlpdb.get("00texlive.config", {}).get("depends", []):
        if dep.startswith("release/"):
            return int(dep.split("/", 1)[1])
    return None


def resolve_packages(
    tlpdb: dict[str, dict], names: list[str], platforms: list[str]
) -> list[str]:
    """Return the packages named and everything they depend on.

    A dependency on ``name.ARCH`` is one on that package's binaries for each
    platform locked.
    """
    unknown = [n for n in names if n not in tlpdb]
    if unknown:
        raise ValueError(
            f"Unknown TeX Live package(s): {', '.join(sorted(unknown))}"
        )
    resolved: set[str] = set()
    queue = list(names)
    while queue:
        name = queue.pop()
        if name in resolved or name not in tlpdb:
            continue
        resolved.add(name)
        for dep in tlpdb[name]["depends"] + EXTRA_DEPENDS.get(name, []):
            if dep.endswith(".ARCH"):
                queue += [dep[:-4] + p for p in platforms]
            elif ":" not in dep and "/" not in dep:
                queue.append(dep)
    # A package listed for one platform only belongs on that one
    return sorted(
        n
        for n in resolved
        if get_package_platform(n) in (None, *platforms)
        and "sha512" in tlpdb[n]
    )


def get_lock_entry(tlpdb: dict[str, dict], name: str) -> dict:
    """Return what a lock records for a package."""
    return {
        "revision": tlpdb[name]["revision"],
        "size": tlpdb[name]["size"],
        "sha512": tlpdb[name]["sha512"],
    }


def create_lock(env: dict, added: list[str] | None = None) -> dict:
    """Resolve an environment's spec into a lock, fetching the database.

    ``added`` are packages builds added beyond the spec, which are kept as
    long as the release has them.
    """
    repository = get_repository_url(env)
    # A moving repository's database is fetched again, since relocking is
    # how a lock it has outgrown is fixed
    tlpdb = load_tlpdb(repository, max_age_s=0)
    platforms = get_lock_platforms(env)
    release = get_tlpdb_release(tlpdb)
    if env.get("release") and int(env["release"]) != release:
        raise ValueError(
            f"TeX Live {env['release']} isn't available; the current "
            f"release is {release}"
        )
    spec_packages = get_spec_packages(env)
    added = sorted(
        p for p in set(added or []) if p in tlpdb and p not in spec_packages
    )
    names = resolve_packages(tlpdb, spec_packages + added, platforms)
    return {
        "lock_format": LOCK_FORMAT_VERSION,
        "spec_hash": calc_spec_hash(env),
        "release": release,
        "repository_url": repository,
        "platforms": platforms,
        "added": added,
        "packages": {n: get_lock_entry(tlpdb, n) for n in names},
    }


def read_lock(lock_fpath: str) -> dict | None:
    """Read a lock, or None if there isn't a usable one."""
    try:
        with open(lock_fpath) as f:
            lock: dict = json.load(f)
    except (OSError, ValueError):
        return None
    if lock.get("lock_format") != LOCK_FORMAT_VERSION:
        return None
    return lock


def write_lock(lock: dict, lock_fpath: str) -> None:
    """Write a lock whole, so it's never read half-written."""
    lock_dir = os.path.dirname(lock_fpath)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    tmp_fpath = f"{lock_fpath}.{os.getpid()}.tmp"
    with open(tmp_fpath, "w", newline="\n") as f:
        json.dump(lock, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp_fpath, lock_fpath)


def get_lock_mutex(lock_fpath: str) -> FileLock:
    """Return a file lock for changing a lock, so concurrent builds don't
    drop each other's packages.

    Kept in the store, so the project gets no extra files.
    """
    from filelock import FileLock

    key = hashlib.md5(os.path.abspath(lock_fpath).encode()).hexdigest()
    mutex_dir = os.path.join(get_store_dir(), "mutexes")
    os.makedirs(mutex_dir, exist_ok=True)
    return FileLock(os.path.join(mutex_dir, key[:16] + ".lock"))


def relock(env_name: str, env: dict, wdir: str | None = None) -> dict:
    """Resolve an environment's lock again, keeping packages builds added,
    and return it.
    """
    lock_fpath = get_lock_fpath(env_name, env, wdir=wdir)
    with get_lock_mutex(lock_fpath):
        old_lock = read_lock(lock_fpath)
        lock = create_lock(env, added=(old_lock or {}).get("added"))
        write_lock(lock, lock_fpath)
    return lock


def get_platform_packages(lock: dict, platform: str) -> dict[str, dict]:
    """Return a lock's packages that belong on a platform."""
    return {
        name: info
        for name, info in lock["packages"].items()
        if get_package_platform(name) in (None, platform)
    }


def get_package_dir(name: str, revision: int) -> str:
    """Return where a package's revision is unpacked in the store."""
    return os.path.join(get_store_dir(), "pkgs", name, str(revision))


def write_ls_r(tree_dir: str) -> None:
    """Write kpathsea's file database for a tree, as mktexlsr would."""
    lines = [
        "% ls-R -- filename database for kpathsea; do not change this line."
    ]
    for dirpath, dirnames, filenames in os.walk(tree_dir):
        dirnames.sort()
        rel = os.path.relpath(dirpath, tree_dir).replace(os.sep, "/")
        lines += ["", "./:" if rel == "." else f"./{rel}:"]
        lines += sorted(dirnames + [f for f in filenames if f != "ls-R"])
    with open(os.path.join(tree_dir, "ls-R"), "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def extract_container(archive_fpath: str, dest_dir: str) -> None:
    """Unpack a package's container into a TeX Live-shaped directory.

    A relocatable package's files are stored relative to ``texmf-dist``,
    which its own description says, so they are moved under it. Paths that
    would escape the destination are refused.
    """
    import tarfile

    dest_real = os.path.realpath(dest_dir)
    with tarfile.open(archive_fpath, "r:xz") as tf:
        for member in tf.getmembers():
            target = os.path.realpath(os.path.join(dest_dir, member.name))
            if not target.startswith(dest_real + os.sep):
                raise ValueError(f"Unsafe path in container: {member.name}")
            if member.isdir():
                os.makedirs(target, exist_ok=True)
            elif member.issym():
                # Links across packages, e.g., a script's launcher in bin,
                # are resolved when an environment is assembled
                if sys.platform == "win32":
                    continue
                link_target = os.path.normpath(
                    os.path.join(os.path.dirname(target), member.linkname)
                )
                if os.path.isabs(member.linkname) or not (
                    link_target.startswith(dest_real + os.sep)
                ):
                    raise ValueError(
                        f"Unsafe link in container: {member.name}"
                    )
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.symlink(member.linkname, target)
            elif member.isfile():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                src = tf.extractfile(member)
                assert src is not None
                with open(target, "wb") as f:
                    shutil.copyfileobj(src, f)
                os.chmod(target, 0o755 if member.mode & 0o111 else 0o644)
    tlpobj_dir = os.path.join(dest_dir, "tlpkg", "tlpobj")
    relocated = False
    if os.path.isdir(tlpobj_dir):
        for fname in os.listdir(tlpobj_dir):
            with open(os.path.join(tlpobj_dir, fname)) as f:
                relocated |= "\nrelocated 1\n" in f.read()
    if relocated:
        texmf_dist = os.path.join(dest_dir, "texmf-dist")
        os.makedirs(texmf_dist)
        for item in os.listdir(dest_dir):
            if item not in ("texmf-dist", "tlpkg"):
                os.rename(
                    os.path.join(dest_dir, item),
                    os.path.join(texmf_dist, item),
                )
    texmf_dist = os.path.join(dest_dir, "texmf-dist")
    if os.path.isdir(texmf_dist):
        write_ls_r(texmf_dist)


def install_packages(
    packages: dict[str, dict],
    repository: str,
    verbose: bool = False,
    n_workers: int = 8,
) -> list[str]:
    """Download and unpack packages missing from the store.

    Each is checked against the checksum its lock recorded. Returns the
    names of those installed.
    """
    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    import requests

    def install(name: str) -> None:
        info = missing[name]
        url = f"{base_url}/archive/{name}.tar.xz"
        with tempfile.TemporaryDirectory(dir=tmp_root) as tmp_dir:
            archive_fpath = os.path.join(tmp_dir, "container.tar.xz")
            sha512 = hashlib.sha512()
            with session.get(url, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with open(archive_fpath, "wb") as f:
                    for chunk in resp.iter_content(1 << 16):
                        sha512.update(chunk)
                        f.write(chunk)
            if sha512.hexdigest() != info["sha512"]:
                raise ValueError(
                    f"TeX Live package '{name}' from {base_url} doesn't "
                    "match its lock; the repository has moved on since it "
                    "was locked, so relock it, or lock a frozen release"
                )
            unpack_dir = os.path.join(tmp_dir, "pkg")
            os.makedirs(unpack_dir)
            extract_container(archive_fpath, unpack_dir)
            with open(os.path.join(unpack_dir, COMPLETE_MARKER), "w") as f:
                f.write(url + "\n")
            pkg_dir = get_package_dir(name, info["revision"])
            os.makedirs(os.path.dirname(pkg_dir), exist_ok=True)
            # Moved into place whole, marker included, so a package's
            # directory is either absent or complete, and one that exists
            # is another process's finished install
            try:
                os.rename(unpack_dir, pkg_dir)
            except OSError:
                if not os.path.isfile(os.path.join(pkg_dir, COMPLETE_MARKER)):
                    raise
        if verbose:
            print(f"Installed {name} r{info['revision']}", file=sys.stderr)

    missing = {
        name: info
        for name, info in packages.items()
        if not os.path.isfile(
            os.path.join(
                get_package_dir(name, info["revision"]), COMPLETE_MARKER
            )
        )
    }
    if not missing:
        return []
    store_dir = get_store_dir()
    tmp_root = os.path.join(store_dir, "tmp")
    os.makedirs(tmp_root, exist_ok=True)
    size_mb = sum(info["size"] for info in missing.values()) / 1e6
    print(
        f"Downloading {len(missing)} TeX Live package(s) ({size_mb:.1f} MB)",
        file=sys.stderr,
    )
    base_url = resolve_mirror(repository)
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        list(pool.map(install, sorted(missing)))
    return sorted(missing)


def calc_view_hash(lock: dict, platform: str) -> str:
    """Hash what an environment on a platform is assembled from."""
    packages = get_platform_packages(lock, platform)
    key = [VIEW_FORMAT_VERSION, platform] + sorted(
        f"{name}:{info['revision']}" for name, info in packages.items()
    )
    return hashlib.md5(json.dumps(key).encode()).hexdigest()


def get_view_dir(lock: dict, platform: str | None = None) -> str:
    """Return where a lock's environment is assembled for a platform."""
    platform = platform or get_platform()
    return os.path.join(
        get_store_dir(), "envs", calc_view_hash(lock, platform)[:16]
    )


def read_executes(pkg_dir: str) -> list[str]:
    """Return a package's install-time actions, from its description."""
    executes = []
    tlpobj_dir = os.path.join(pkg_dir, "tlpkg", "tlpobj")
    if not os.path.isdir(tlpobj_dir):
        return []
    for fname in sorted(os.listdir(tlpobj_dir)):
        with open(os.path.join(tlpobj_dir, fname)) as f:
            executes += [
                line[len("execute ") :].strip()
                for line in f
                if line.startswith("execute ")
            ]
    return executes


def parse_execute_args(args: str) -> dict[str, str]:
    """Parse an action's key=value words, honoring double quotes."""
    import shlex

    parsed = {}
    for word in shlex.split(args, posix=True):
        key, _, value = word.partition("=")
        parsed[key] = value
    return parsed


def link_file(src: str, dst: str) -> None:
    """Hard link a file into an environment, copying if that can't work.

    Hard links need no privileges on Windows, unlike symbolic links, and
    the store and its environments share a volume, so they work wherever
    the store does. Unlike a symbolic link, one also leaves a program
    believing it lives in the environment, which is how TeX finds the
    environment's configuration.
    """
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def get_thin_program_fpath(fpath: str) -> str:
    """Return a macOS program built for this machine alone, if it's a
    universal one that would unpack itself to run.

    Biber's does, with Xcode's ``lipo``, which isn't on every Mac and
    doesn't take the option it uses on every version, so its slice is
    unpacked here instead, once, into the store. Anything else is returned
    as is.
    """
    import platform
    import struct

    cpu_types = {"arm64": 0x0100000C, "x86_64": 0x01000007}
    cpu_type = cpu_types.get(platform.machine())
    with open(fpath, "rb") as f:
        header = f.read(8)
        if len(header) < 8 or cpu_type is None:
            return fpath
        magic, n_archs = struct.unpack(">II", header)
        if magic not in (0xCAFEBABE, 0xCAFEBABF):
            return fpath
        fmt = ">iiQQII" if magic == 0xCAFEBABF else ">iiIII"
        archs = [
            struct.unpack(fmt, f.read(struct.calcsize(fmt)))
            for _ in range(n_archs)
        ]
        arch = next((a for a in archs if a[0] == cpu_type), None)
        if arch is None:
            return fpath
        offset, size = arch[2], arch[3]
        # The unpacking launcher's code is at its start
        f.seek(offset)
        if b"-extract_family" not in f.read(min(size, 1 << 21)):
            return fpath
        key = hashlib.md5(f"{fpath}:{cpu_type}".encode()).hexdigest()[:16]
        thin_fpath = os.path.join(
            get_store_dir(), "thin", key, os.path.basename(fpath)
        )
        if os.path.isfile(thin_fpath):
            return thin_fpath
        os.makedirs(os.path.dirname(thin_fpath), exist_ok=True)
        tmp_fpath = f"{thin_fpath}.{os.getpid()}.tmp"
        f.seek(offset)
        with open(tmp_fpath, "wb") as out:
            remaining = size
            while remaining:
                chunk = f.read(min(remaining, 1 << 20))
                out.write(chunk)
                remaining -= len(chunk)
    os.chmod(tmp_fpath, 0o755)
    os.replace(tmp_fpath, thin_fpath)
    return thin_fpath


def create_language_files(
    pkg_dirs: dict[str, str], out_dir: str
) -> dict[str, str]:
    """Write the hyphenation pattern lists the formats are built from.

    These are what ``tlmgr generate language`` writes from the AddHyphen
    actions of the packages installed: language.dat for pdfTeX,
    language.def for e-TeX's own loader, and language.dat.lua for LuaTeX.
    Returns each file's content, which the formats depend on.
    """
    config_rel = os.path.join("tex", "generic", "config")
    head_dir = os.path.join(pkg_dirs["hyphen-base"], "texmf-dist", config_rel)
    dat: list[str] = []
    dfn: list[str] = []
    lua: list[str] = []
    for name in sorted(pkg_dirs):
        langs = [
            parse_execute_args(e[len("AddHyphen") :])
            for e in read_executes(pkg_dirs[name])
            if e.startswith("AddHyphen")
        ]
        if not langs:
            continue
        for lines, db, cc in (
            (dat, "dat", "%"),
            (dfn, "def", "%"),
            (lua, "lua", "--"),
        ):
            first = True
            for lang in langs:
                if db not in lang.get("databases", "dat,def,lua").split(","):
                    continue
                if first:
                    lines.append(f"{cc} from {name}:\n")
                    first = False
                if lang.get("comment"):
                    lines.append(f"{cc} {lang['comment']}\n")
                syns = [s for s in lang.get("synonyms", "").split(",") if s]
                lhm = lang.get("lefthyphenmin", "")
                rhm = lang.get("righthyphenmin", "")
                if db == "dat":
                    lines.append(f"{lang['name']} {lang['file']}\n")
                    lines += [f"={s}\n" for s in syns]
                elif db == "def":
                    for n in [lang["name"]] + syns:
                        lines.append(
                            f"\\addlanguage{{{n}}}{{{lang['file']}}}{{}}"
                            f"{{{lhm}}}{{{rhm}}}\n"
                        )
                else:
                    entry = [
                        f"['{lang['name']}'] = {{",
                        f"\tloader = '{lang['file']}',",
                        f"\tlefthyphenmin = {lhm},",
                        f"\trighthyphenmin = {rhm},",
                        "\tsynonyms = { "
                        + ", ".join(f"'{s}'" for s in syns)
                        + " },",
                    ]
                    for key, field in (
                        ("patterns", "file_patterns"),
                        ("hyphenation", "file_exceptions"),
                        ("special", "luaspecial"),
                    ):
                        if lang.get(field):
                            entry.append(f"\t{key} = '{lang[field]}',")
                    entry.append("},")
                    lines += [f"\t{e}\n" for e in entry]
    def_tail = [
        "%%% No changes may be made beyond this point.\n",
        "\n",
        "\\uselanguage {USenglish}             %%% This MUST be the last "
        "line of the file.\n",
    ]
    contents = {}
    for fname, head, lines, tail, cc in (
        ("language.dat", "language.us", dat, [], "%"),
        ("language.def", "language.us.def", dfn, def_tail, "%"),
        ("language.dat.lua", "language.us.lua", lua, ["}\n"], "--"),
    ):
        with open(os.path.join(head_dir, head)) as f:
            head_text = f.read()
        # language.def's first line identifies it, so it stays first
        generated = (
            "" if fname == "language.def" else (f"{cc} Generated by Calkit\n")
        )
        contents[fname] = generated + head_text + "".join(lines + tail)
        fpath = os.path.join(out_dir, config_rel, fname)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", newline="\n") as f:
            f.write(contents[fname])
    return contents


def create_font_maps(pkg_dirs: dict[str, str], out_dir: str) -> None:
    """Write the font maps pdfTeX and dvips read, as updmap would.

    The concatenation of every map file packages register, keeping the
    first entry for each font.
    """
    maps = []
    for name in sorted(pkg_dirs):
        for e in read_executes(pkg_dirs[name]):
            kind, _, fname = e.partition(" ")
            if kind in ("addMap", "addMixedMap"):
                maps.append((name, fname.strip()))
    seen: set[str] = set()
    lines = ["% Generated by Calkit from the packages' font maps\n"]
    for name, fname in maps:
        found = None
        for candidate in [name] + sorted(pkg_dirs):
            fonts_dir = os.path.join(
                pkg_dirs[candidate], "texmf-dist", "fonts"
            )
            for dirpath, _, filenames in os.walk(fonts_dir):
                if (
                    fname in filenames
                    and "/map/" in dirpath.replace(os.sep, "/") + "/"
                ):
                    found = os.path.join(dirpath, fname)
                    break
            if found:
                break
        if found is None:
            continue
        with open(found, encoding="latin-1") as f:
            for line in f:
                words = line.split()
                if not words or line.startswith(("%", "#")):
                    continue
                if words[0] in seen:
                    continue
                seen.add(words[0])
                lines.append(line if line.endswith("\n") else line + "\n")
    # xdvipdfmx asks for a Japanese font map too, which updmap writes
    # whether or not there are any such fonts
    for rel, content in (
        (
            os.path.join("fonts", "map", "pdftex", "updmap", "pdftex.map"),
            lines,
        ),
        (
            os.path.join("fonts", "map", "dvips", "updmap", "psfonts.map"),
            lines,
        ),
        (os.path.join("fonts", "map", "dvipdfmx", "updmap", "kanjix.map"), []),
    ):
        fpath = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="latin-1", newline="\n") as f:
            f.writelines(content)


def assemble_view(lock: dict, platform: str, verbose: bool = False) -> str:
    """Assemble a lock's environment for a platform from the store.

    Builds in a temporary directory and moves it into place, so an
    interrupted build is never mistaken for a finished one. Returns the
    environment's directory.
    """
    import shlex
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    from xml.sax.saxutils import escape

    def build_format(fmt: dict[str, str], fmt_dir: str) -> None:
        """Build a format into the store, as fmtutil would.

        One other than LaTeX's that fails is skipped with a warning, as
        fmtutil does, since a package can register a format the document
        never uses.
        """
        name = fmt["name"]
        print(f"Building TeX format {name}", file=sys.stderr)
        tmp_root = os.path.join(get_store_dir(), "tmp")
        os.makedirs(tmp_root, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_root) as tmp_dir:
            cmd = [
                os.path.join(bin_dir, fmt["engine"] + exe),
                "-ini",
                f"-jobname={name}",
                f"-progname={name}",
            ] + shlex.split(fmt.get("options", ""))
            result = subprocess.run(
                cmd,
                cwd=tmp_dir,
                env=env_vars,
                stdin=subprocess.DEVNULL,
                capture_output=not verbose,
            )
            built = os.path.join(tmp_dir, name + ".fmt")
            if result.returncode or not os.path.isfile(built):
                log = os.path.join(tmp_dir, name + ".log")
                tail = ""
                if os.path.isfile(log):
                    with open(log, errors="replace") as f:
                        tail = "".join(f.readlines()[-20:])
                msg = f"TeX format {name} failed to build:\n{tail}"
                if name in LATEX_FORMATS:
                    raise RuntimeError(msg)
                print(f"Warning: skipping it; {msg}", file=sys.stderr)
                return
            os.makedirs(fmt_dir, exist_ok=True)
            os.replace(built, os.path.join(fmt_dir, name + ".fmt"))

    def find_source(rel: str) -> str | None:
        # Follows links within the environment's layout to a real file
        for _ in range(16):
            fpath = owners.get(rel)
            if fpath is None and rel.startswith("texmf-dist/"):
                for name in sorted(pkg_dirs):
                    candidate = os.path.join(pkg_dirs[name], rel)
                    if os.path.lexists(candidate):
                        fpath = candidate
                        break
            if fpath is None:
                return None
            if not os.path.islink(fpath):
                return fpath
            rel = os.path.normpath(
                os.path.join(os.path.dirname(rel), os.readlink(fpath))
            ).replace(os.sep, "/")
        return None

    view_dir = get_view_dir(lock, platform)
    if os.path.isfile(os.path.join(view_dir, COMPLETE_MARKER)):
        return view_dir
    packages = get_platform_packages(lock, platform)
    pkg_dirs = {
        name: get_package_dir(name, info["revision"])
        for name, info in packages.items()
    }
    store_dir = get_store_dir()
    os.makedirs(os.path.join(store_dir, "envs"), exist_ok=True)
    tmp_dir = tempfile.mkdtemp(dir=os.path.join(store_dir, "envs"))
    # Removed if anything fails, so a half-built one doesn't linger
    try:
        exe = ".exe" if platform == "windows" else ""
        # Programs and anything else a platform package carries outside the TeX
        # tree, e.g., Windows' Perl under tlpkg, go in by hard link, resolving
        # the symbolic links that point from one package into another
        owners: dict[str, str] = {}
        for name in sorted(pkg_dirs):
            if get_package_platform(name) is None:
                continue
            pkg_dir = pkg_dirs[name]
            for dirpath, _, filenames in os.walk(pkg_dir):
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    rel = os.path.relpath(fpath, pkg_dir).replace(os.sep, "/")
                    if (
                        rel.startswith("tlpkg/tlpobj/")
                        or fname == COMPLETE_MARKER
                    ):
                        continue
                    owners.setdefault(rel, fpath)
        for rel in sorted(owners):
            src = find_source(rel)
            if src is None:
                continue
            if platform == "universal-darwin" and rel.startswith("bin/"):
                src = get_thin_program_fpath(src)
            link_file(src, os.path.join(tmp_dir, rel))
        # Windows' script launchers look for their Lua driver beside the
        # programs, as in a full TeX Live
        for rel in (
            "texmf-dist/scripts/texlive/runscript.tlu",
            "texmf-dist/web2c/texmf.cnf",
        ):
            src = find_source(rel)
            if src is not None:
                link_file(src, os.path.join(tmp_dir, rel))
        # Every package's tree stays where it is in the store, each with its
        # own file database, and kpathsea searches them all. The environment's
        # own tree holds what's generated for it.
        trees = sorted(
            os.path.join(d, "texmf-dist").replace(os.sep, "/")
            for d in pkg_dirs.values()
            if os.path.isdir(os.path.join(d, "texmf-dist"))
        )
        cnf = [
            "% Generated by Calkit for a TeX Live environment",
            "TEXMFROOT = $SELFAUTOPARENT",
            "TEXMFDIST = {" + ",".join(trees) + "}",
            "TEXMFVAR = $SELFAUTOPARENT/texmf-var",
            "TEXMFCONFIG = $SELFAUTOPARENT/texmf-var",
            "TEXMFSYSVAR = $SELFAUTOPARENT/texmf-var",
            "TEXMFSYSCONFIG = $SELFAUTOPARENT/texmf-var",
            "TEXMFLOCAL = $SELFAUTOPARENT/texmf-var",
            # Nothing from the user's own trees, so a build only sees what the
            # lock pins
            "TEXMFHOME = $SELFAUTOPARENT/texmf-home",
            "TEXMFAUXTREES = {}",
            # Fonts are looked for in the environment, not the system
            "OSFONTDIR = $SELFAUTOPARENT/texmf-home",
        ]
        with open(os.path.join(tmp_dir, "texmf.cnf"), "w", newline="\n") as f:
            f.write("\n".join(cnf) + "\n")
        var_dir = os.path.join(tmp_dir, "texmf-var")
        os.makedirs(var_dir)
        languages = create_language_files(pkg_dirs, var_dir)
        create_font_maps(pkg_dirs, var_dir)
        # LuaTeX looks for fonts in TeX's trees only, not the system's, which
        # also saves it indexing every font on the machine
        luaotfload_conf = os.path.join(
            var_dir, "tex", "generic", "config", "luaotfload.conf"
        )
        with open(luaotfload_conf, "w", newline="\n") as f:
            f.write("[db]\n    location-precedence = texmf,local\n")
        # XeTeX does the same through fontconfig, which reads this, except on
        # macOS, where it also sees the system's. It's written for where the
        # environment ends up, since fontconfig writes its cache there.
        font_dirs = sorted(
            os.path.join(tree, "fonts", kind)
            for tree in trees
            for kind in ("opentype", "truetype", "type1")
            if os.path.isdir(os.path.join(tree, "fonts", kind))
        )
        fonts_conf = [
            '<?xml version="1.0"?>',
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">',
            "<fontconfig>",
            *(f"  <dir>{escape(d)}</dir>" for d in font_dirs),
            "  <cachedir>"
            + escape(
                os.path.join(view_dir, "texmf-var", "fonts", "cache").replace(
                    os.sep, "/"
                )
            )
            + "</cachedir>",
            "</fontconfig>",
        ]
        os.makedirs(os.path.join(var_dir, "fonts", "conf"))
        with open(
            os.path.join(var_dir, "fonts", "conf", "fonts.conf"),
            "w",
            newline="\n",
        ) as f:
            f.write("\n".join(fonts_conf) + "\n")
        # Formats depend on their engine and the packages TeX Live says trigger
        # a rebuild, so they're cached in the store by a hash of those, and an
        # environment that differs only in, e.g., siunitx, reuses them
        bin_dir = os.path.join(tmp_dir, "bin", platform)
        env_vars = get_run_env_vars(tmp_dir, platform)
        engine_pkgs = {
            os.path.basename(rel): os.path.relpath(src, store_dir)
            .replace(os.sep, "/")
            .split("/")[1]
            for rel, src in owners.items()
            if rel.startswith(f"bin/{platform}/")
        }
        write_ls_r(var_dir)
        formats: list[tuple[dict[str, str], str]] = []
        for name in sorted(pkg_dirs):
            for e in read_executes(pkg_dirs[name]):
                if not e.startswith("AddFormat"):
                    continue
                fmt = parse_execute_args(e[len("AddFormat") :])
                engine = fmt.get("engine", "")
                if fmt.get("mode") == "disabled" or not os.path.isfile(
                    os.path.join(bin_dir, engine + exe)
                ):
                    continue
                if engine in ("mpost", "mf", "mf-nowin"):
                    continue
                key_parts = [
                    platform,
                    e,
                    f"kpathsea.{platform}:"
                    f"{packages.get(f'kpathsea.{platform}', {}).get('revision')}",
                ]
                engine_pkg = engine_pkgs.get(engine + exe, "")
                key_parts.append(
                    f"{engine_pkg}:{packages.get(engine_pkg, {}).get('revision')}"
                )
                for trigger in fmt.get("fmttriggers", "").split(","):
                    key_parts.append(
                        f"{trigger}:{packages.get(trigger, {}).get('revision')}"
                    )
                for pattern in fmt.get("patterns", "").split(","):
                    key_parts.append(languages.get(pattern, ""))
                key = hashlib.md5("\n".join(key_parts).encode()).hexdigest()
                fmt_dir = os.path.join(
                    store_dir, "formats", f"{fmt['name']}-{key[:16]}"
                )
                formats.append((fmt, fmt_dir))
        # In parallel, since each is one process and LaTeX's take a while
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as pool:
            list(
                pool.map(
                    lambda job: build_format(*job),
                    [
                        (fmt, fmt_dir)
                        for fmt, fmt_dir in formats
                        if not os.path.isfile(
                            os.path.join(fmt_dir, fmt["name"] + ".fmt")
                        )
                    ],
                )
            )
        for fmt, fmt_dir in formats:
            if not os.path.isfile(os.path.join(fmt_dir, fmt["name"] + ".fmt")):
                continue
            link_file(
                os.path.join(fmt_dir, fmt["name"] + ".fmt"),
                os.path.join(
                    var_dir, "web2c", fmt["engine"], fmt["name"] + ".fmt"
                ),
            )
        write_ls_r(var_dir)
        with open(os.path.join(tmp_dir, COMPLETE_MARKER), "w") as f:
            f.write(json.dumps(sorted(packages)) + "\n")
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    try:
        os.rename(tmp_dir, view_dir)
    except OSError:
        # Another process assembled the same environment first
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if not os.path.isfile(os.path.join(view_dir, COMPLETE_MARKER)):
            raise
    return view_dir


def get_run_env_vars(
    view_dir: str, platform: str | None = None, env_vars: dict | None = None
) -> dict:
    """Return the environmental variables a command in an environment gets.

    These are ``env_vars``, by default this process's, with the
    environment's programs first on PATH, and every variable
    kpathsea would take from the environment over ``texmf.cnf``, e.g.,
    ``TEXINPUTS`` or ``TEXINPUTS.xelatex``, is dropped. Nothing else is
    needed for TeX: the programs find the environment's configuration from
    where they are. XeTeX's fontconfig doesn't, except on Windows, so it's
    pointed at the environment's.
    """
    platform = platform or get_platform()
    names = set(LEAKY_ENV_VARS)
    cnf_fpath = os.path.join(view_dir, "texmf-dist", "web2c", "texmf.cnf")
    if os.path.isfile(cnf_fpath):
        with open(cnf_fpath, encoding="utf-8", errors="replace") as f:
            names.update(re.findall(r"(?m)^([A-Z][A-Z0-9_]*)[\s.=]", f.read()))
    # kpathsea also reads VAR.program and VAR_program
    pattern = re.compile(
        "(" + "|".join(sorted(names)) + r")([._][A-Za-z0-9_-]+)?",
        re.IGNORECASE,
    )
    env_vars = {
        k: v
        for k, v in (os.environ if env_vars is None else env_vars).items()
        if not pattern.fullmatch(k)
    }
    bin_dir = os.path.join(view_dir, "bin", platform)
    env_vars["PATH"] = bin_dir + os.pathsep + env_vars.get("PATH", "")
    env_vars["FONTCONFIG_FILE"] = os.path.join(
        view_dir, "texmf-var", "fonts", "conf", "fonts.conf"
    )
    return env_vars


def get_lock_fpath(env_name: str, env: dict, wdir: str | None = None) -> str:
    """Return where an environment's lock lives in the project, or in the
    store for the default environment.
    """
    from calkit.environments import get_env_lock_fpath

    if env_name == DEFAULT_ENV_NAME:
        return os.path.join(get_store_dir(), "default-lock.json")
    lock_fpath = get_env_lock_fpath(
        env=env, env_name=env_name, wdir=wdir, as_posix=False
    )
    assert lock_fpath is not None
    return lock_fpath


def check(
    env_name: str,
    env: dict,
    rebuild: bool = False,
    verbose: bool = False,
    wdir: str | None = None,
) -> str:
    """Make sure an environment is locked and assembled here.

    The lock is only resolved again when the spec changed, which a hash in
    it says, so a check of an environment that's ready is reading one small
    file and seeing that a directory exists. ``rebuild`` assembles the
    environment again, though not the packages or formats it's assembled
    from, which never change once in the store. Returns the environment's
    directory.
    """
    lock_fpath = get_lock_fpath(env_name, env, wdir=wdir)
    lock = read_lock(lock_fpath)
    if lock is None or lock.get("spec_hash") != calc_spec_hash(env):
        print(f"Locking TeX Live environment '{env_name}'", file=sys.stderr)
        lock = relock(env_name, env, wdir=wdir)
    platform = get_platform()
    if platform not in lock["platforms"]:
        raise ValueError(
            f"TeX Live environment '{env_name}' isn't locked for "
            f"{platform}; add it to the environment's 'platforms'"
        )
    view_dir = get_view_dir(lock, platform)
    if rebuild and os.path.isdir(view_dir):
        shutil.rmtree(view_dir)
    if not os.path.isfile(os.path.join(view_dir, COMPLETE_MARKER)):
        install_packages(
            get_platform_packages(lock, platform),
            lock["repository_url"],
            verbose=verbose,
        )
        assemble_view(lock, platform, verbose=verbose)
    return view_dir


def warm(env: dict, verbose: bool = False) -> str:
    """Install and assemble an environment from its spec alone, without a
    project or a lock written anywhere, and return its directory.

    Fills the store ahead of time, e.g., in a dev container image, so a
    project's first build reuses the packages and formats rather than
    downloading and building them.
    """
    lock = create_lock(env)
    platform = get_platform()
    if platform not in lock["platforms"]:
        raise ValueError(f"TeX Live environments aren't locked for {platform}")
    view_dir = get_view_dir(lock, platform)
    if not os.path.isfile(os.path.join(view_dir, COMPLETE_MARKER)):
        install_packages(
            get_platform_packages(lock, platform),
            lock["repository_url"],
            verbose=verbose,
        )
        assemble_view(lock, platform, verbose=verbose)
    return view_dir


def get_run_cmd(cmd: list[str], env_vars: dict) -> list[str]:
    """Return a command with its program looked up on an environment's PATH.

    On Windows, a child's program is found on the parent's PATH, not the
    one it's given.
    """
    if cmd:
        found = shutil.which(cmd[0], path=env_vars["PATH"])
        if found is not None:
            return [found] + cmd[1:]
    return cmd


def run(
    view_dir: str,
    cmd: list[str],
    wdir: str | None = None,
    verbose: bool = False,
) -> int:
    """Run a command in an assembled environment, returning its status."""
    env_vars = get_run_env_vars(view_dir)
    cmd = get_run_cmd(cmd, env_vars)
    if verbose:
        print(f"Running command: {cmd}", file=sys.stderr)
    return subprocess.call(cmd, cwd=wdir, env=env_vars)


def find_packages_for_files(
    lock: dict, filenames: list[str]
) -> dict[str, str]:
    """Look up which packages provide files TeX couldn't find.

    Uses the database cached when the environment was locked, so the
    packages come from the same repository and release. Returns each file
    found mapped to its package; files no package provides are left out.
    Where several packages have a file, a release's copy wins over the
    LaTeX development format's, e.g., tools' array.sty over
    latex-tools-dev's.
    """
    tlpdb = load_tlpdb(lock["repository_url"])
    wanted = {"/" + f: f for f in filenames}
    candidates: dict[str, list[tuple[int, str]]] = {}
    for name in sorted(tlpdb):
        for path in tlpdb[name]["runfiles"]:
            if "/" + path.rsplit("/", 1)[-1] not in wanted:
                continue
            fname = wanted["/" + path.rsplit("/", 1)[-1]]
            rank = int("/latex-dev/" in path or name.endswith("-dev"))
            candidates.setdefault(fname, []).append((rank, name))
    # cm-super's outlines for the EC and TC fonts, i.e., T1- and
    # TS1-encoded Computer Modern, are named after the fonts it maps them
    # from, e.g., sfrm1000.pfb for ecrm1000
    for fname in filenames:
        if re.fullmatch(r"(ec|tc)[a-z]{2}\d{4}\.pfb", fname):
            candidates.setdefault(fname, []).append((0, "cm-super"))
    return {
        fname: min(found)[1]
        for fname, found in candidates.items()
        if fname in filenames and min(found)[1] in tlpdb
    }


def add_document_packages(
    env_name: str,
    env: dict,
    tex_file: str,
    wdir: str | None = None,
    max_rounds: int = 10,
) -> dict[str, str]:
    """Add the packages a document needs that its environment doesn't have.

    TeX Live's database doesn't say what most packages need, so this reads
    it from the files: the classes, packages, and bibliography styles the
    document names, then those named by the packages added for them, and
    so on, asking the environment's own kpsewhich which it can't find. A
    new document gets everything it needs in a few lookups rather than one
    failed compile per package. A name a package only loads conditionally
    is added too, which costs a little space rather than a failed build.
    What's added goes in the lock, not the spec.

    Returns each missing file mapped to the package added for it.
    """
    from pathlib import Path

    lock_fpath = get_lock_fpath(env_name, env, wdir=wdir)
    added_for: dict[str, str] = {}
    files = [tex_file]
    for _ in range(max_rounds):
        names = list(
            dict.fromkeys(
                name
                for fpath in files
                for name in calkit.latex.find_named_tex_files(fpath)
                if name not in added_for
            )
        )
        if not names:
            break
        view_dir = check(env_name, env, wdir=wdir)
        env_vars = get_run_env_vars(view_dir)
        result = subprocess.run(
            get_run_cmd(["kpsewhich", *names], env_vars),
            cwd=os.path.dirname(tex_file) or ".",
            env=env_vars,
            capture_output=True,
            text=True,
        )
        found = {
            os.path.basename(line.strip())
            for line in result.stdout.splitlines()
            if line.strip()
        }
        missing = [n for n in names if n not in found]
        lock = read_lock(lock_fpath)
        if not missing or lock is None:
            break
        owners = find_packages_for_files(lock, missing)
        added = add_packages(env_name, env, list(owners.values()), wdir=wdir)
        added_for.update(owners)
        if not added:
            break
        check(env_name, env, wdir=wdir)
        lock = read_lock(lock_fpath) or lock
        files = [
            str(fpath)
            for name in added
            for fpath in sorted(
                Path(
                    get_package_dir(name, lock["packages"][name]["revision"])
                ).glob("texmf-dist/tex/**/*")
            )
            if fpath.suffix in (".sty", ".cls")
        ]
    return added_for


def check_with_extra_packages(
    env_name: str,
    env: dict,
    packages: list[str],
    verbose: bool = False,
    wdir: str | None = None,
) -> str:
    """Assemble an environment with packages beyond its lock, without
    adding them to it, and return its directory.

    For a one-off task outside the pipeline, e.g., converting a document
    to .docx. The packages come from the lock's repository, like the
    locked ones, and the environment is kept in the store for next time.
    """
    check(env_name, env, verbose=verbose, wdir=wdir)
    lock = read_lock(get_lock_fpath(env_name, env, wdir=wdir))
    assert lock is not None
    tlpdb = load_tlpdb(lock["repository_url"])
    lock = lock | {"packages": dict(lock["packages"])}
    for name in resolve_packages(tlpdb, packages, lock["platforms"]):
        lock["packages"].setdefault(name, get_lock_entry(tlpdb, name))
    platform = get_platform()
    view_dir = get_view_dir(lock, platform)
    if not os.path.isfile(os.path.join(view_dir, COMPLETE_MARKER)):
        install_packages(
            get_platform_packages(lock, platform),
            lock["repository_url"],
            verbose=verbose,
        )
        assemble_view(lock, platform, verbose=verbose)
    return view_dir


def add_packages(
    env_name: str, env: dict, packages: list[str], wdir: str | None = None
) -> list[str]:
    """Add packages a build found missing to an environment's lock.

    The spec stays as written. The lock lists what was added beyond it,
    which relocking keeps, so the next build anywhere has them; deleting
    the lock drops them, and builds add back what's still needed.

    Returns those that weren't already locked.
    """
    lock_fpath = get_lock_fpath(env_name, env, wdir=wdir)
    with get_lock_mutex(lock_fpath):
        lock = read_lock(lock_fpath)
        if lock is None:
            raise ValueError(f"TeX Live environment '{env_name}' isn't locked")
        added = [
            p for p in dict.fromkeys(packages) if p not in lock["packages"]
        ]
        if not added:
            return []
        tlpdb = load_tlpdb(lock["repository_url"])
        for name in resolve_packages(tlpdb, added, lock["platforms"]):
            lock["packages"].setdefault(name, get_lock_entry(tlpdb, name))
        lock["added"] = sorted(set(lock.get("added", [])) | set(added))
        write_lock(lock, lock_fpath)
    return added


def get_selected_env(
    env_name: str | None, wdir: str | None = None
) -> tuple[str, dict] | None:
    """Return the TeX Live environment a name runs in here, if it's one.

    A switch is resolved to the option it picks on this machine.
    """
    from calkit.environments import SWITCH_KIND, get_env, resolve_switch

    if env_name is None:
        return None
    envs = calkit.load_calkit_info(wdir=wdir, read_only=True).get(
        "environments", {}
    )
    env = get_env(env_name, envs)
    if env is not None and env.get("kind") == SWITCH_KIND:
        try:
            picked = resolve_switch(env_name, envs)
        except ValueError:
            return None
        if picked is None:
            return None
        env_name, env = picked, get_env(picked, envs)
    if env is None or env.get("kind") != "texlive":
        return None
    return env_name, env
