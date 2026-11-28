"""Deterministic tar archives of projects that keep their timestamps.

Entries are sorted and owned by no one, and gzip records no time, so the
same files with the same modification times give the same bytes.
Modification times are kept because they're part of a project's state:
make reads them, and the messy arms' history lives in them.
"""

import gzip
import os
import tarfile
from collections.abc import Callable
from pathlib import Path

# What a trial's archived project leaves out: environments, which are
# rebuilt, and Calkit's and DVC's local caches and state
RUN_SKIP_NAMES = {".venv", "venv"}
RUN_SKIP_PATHS = {".dvc/cache", ".dvc/tmp", ".calkit/local"}


def skip_run_path(rel: str) -> bool:
    return rel in RUN_SKIP_PATHS or Path(rel).name in RUN_SKIP_NAMES


def pack(
    src: Path,
    dest: Path,
    skip: Callable[[str], bool] = lambda rel: False,
    clamp_after: float | None = None,
    clamp_to: float | None = None,
) -> None:
    """Archive src's contents into dest, a .tar.gz.

    Paths for which `skip` is true are left out, with everything under
    them. Times later than `clamp_after` become `clamp_to`, so files whose
    times only say when the build ran, e.g., Git's internals, don't make
    two builds differ.
    """

    def get_info(path: Path, rel: str) -> tarfile.TarInfo:
        info = tar.gettarinfo(str(path), arcname=rel)
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        if clamp_after is not None and clamp_to is not None:
            if info.mtime > clamp_after:
                info.mtime = clamp_to
        return info

    dest.parent.mkdir(parents=True, exist_ok=True)
    with (
        open(dest, "wb") as f,
        gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for dirpath, dirnames, filenames in os.walk(src):
            rel_dir = Path(dirpath).relative_to(src)
            dirnames[:] = sorted(
                d for d in dirnames if not skip((rel_dir / d).as_posix())
            )
            if rel_dir != Path("."):
                tar.addfile(get_info(Path(dirpath), rel_dir.as_posix()))
            # Symlinks to directories are listed with the directories
            names = sorted(
                filenames
                + [d for d in dirnames if (Path(dirpath) / d).is_symlink()]
            )
            for name in names:
                rel = (rel_dir / name).as_posix()
                if skip(rel):
                    continue
                path = Path(dirpath) / name
                info = get_info(path, rel)
                if info.isreg():
                    with open(path, "rb") as content:
                        tar.addfile(info, content)
                else:
                    tar.addfile(info)
            dirnames[:] = [
                d for d in dirnames if not (Path(dirpath) / d).is_symlink()
            ]


def unpack(archive: Path, dest: Path) -> None:
    """Extract an archive pack wrote, keeping its times and modes."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter="tar")
