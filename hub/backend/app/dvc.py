"""Functionality for working with DVC."""

import concurrent.futures
import glob
import json
import logging
import os
import subprocess
import sys
import tempfile
from functools import lru_cache

import ruamel.yaml
from dvc.commands import dag
from dvc.repo import Repo

import calkit.dvc
from app.storage import get_object_fs, make_data_fpath

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
yaml = ruamel.yaml.YAML()

# Teach DVC about the ck:// remote scheme, which projects use by default.
# This must happen before anything in this process validates a DVC config,
# since DVC memoizes its compiled config schema (dvc.config.
# get_compiled_schema) on first use. Without it, once something here has
# touched a DVC config (e.g. make_mermaid_diagram), every later ck:// config
# read in the same worker fails with "Unsupported URL type ck://", which is
# how project creation ended up 500ing after the project row was written.
calkit.dvc.register_ck_scheme()


def run_dvc_command(args: list[str], wdir: str, check: bool = False) -> int:
    """Run a DVC CLI command in a subprocess with ck:// support registered.

    Goes through ``calkit dvc`` rather than ``dvc`` directly so the child
    process registers the ck:// scheme; a plain ``dvc`` call fails in any
    project whose remote is ck://.
    """
    cmd = [sys.executable, "-m", "calkit", "dvc"] + args
    logger.info(f"Running {' '.join(cmd)} in {wdir}")
    if check:
        return subprocess.check_call(cmd, cwd=wdir)
    return subprocess.call(cmd, cwd=wdir)


@lru_cache(maxsize=512)
def _read_dvc_dir_cached(dvc_dir_path: str) -> list[dict] | None:
    """Cache DVC .dir file contents by path.

    Returns None if file doesn't exist.
    """
    fs = get_object_fs()
    try:
        with fs.open(dvc_dir_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def make_mermaid_diagram(pipeline: dict, params: dict | None = None) -> str:
    """Create a Mermaid diagram from a pipeline file (typically ``dvc.yaml``).

    This is a little hacky since we need to create a Git and DVC repo in order
    to run the commands in DVC.
    """
    wd_orig = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as tmpdirname:
            os.chdir(tmpdirname)
            with open("dvc.yaml", "w") as f:
                yaml.dump(pipeline, f)
            if params is not None:
                with open("params.yaml", "w") as f:
                    yaml.dump(params, f)
            with Repo.init(
                ".",
                no_scm=True,
                force=False,
                subdir=False,
            ) as repo:
                d = dag._build(repo)
            mm = dag._show_mermaid(d, markdown=False)
    finally:
        os.chdir(wd_orig)
    return mm


def output_from_pipeline(
    path: str, stage_name: str, pipeline: dict, lock: dict
) -> dict | None:
    """Given a path and stage name, search through the DVC pipeline config and
    DVC lock files to see if the path exists as a DVC output.

    What is returned will look like a single DVC output object, e.g.,

        - path: environment.lock.yml
          hash: md5
          md5: cacb2fa264cff6fd46c76da5de7645ac
          size: 9536

    """
    stage = pipeline.get("stages", {}).get(stage_name.split("@")[0])
    if stage is None:
        return
    wdir = stage.get("wdir", "")
    outs = lock.get("stages", {}).get(stage_name, {}).get("outs", [])
    for out in outs:
        outpath = os.path.join(wdir, out["path"])
        if os.path.abspath(outpath) == os.path.abspath(path):
            out["path"] = path
            return out
    # If there's only one output, no need to check path if we don't have an
    # exact match
    if len(outs) == 1:
        return outs[0]


def get_data_fpath_for_md5(
    owner_name: str,
    project_name: str,
    md5: str,
    fs=None,
) -> str | None:
    """Return the first existing object-storage path for a DVC MD5.

    Supports both the current `files/md5` layout and the legacy layout.
    """
    if not md5 or len(md5) < 3:
        return None
    if fs is None:
        fs = get_object_fs()
    idx = md5[:2]
    candidates = [
        make_data_fpath(
            owner_name=owner_name,
            project_name=project_name,
            idx=idx,
            md5=md5[2:],
            legacy=False,
        ),
        make_data_fpath(
            owner_name=owner_name,
            project_name=project_name,
            idx=idx,
            md5=md5[2:],
            legacy=True,
        ),
    ]
    for candidate in candidates:
        try:
            if fs.exists(candidate):
                return candidate
        except Exception as e:
            logger.warning(f"Failed existence check for {candidate}: {e}")
    return None


def find_dvc_files(start: str, max_depth=5) -> list[str]:
    """Find all DVC files in the repo."""
    res = []
    for i in range(max_depth):
        pattern = os.path.join(start, *["*"] * (i + 1), "*.dvc")
        res += glob.glob(pattern)
        res += glob.glob(pattern)
    return res


def expand_dvc_lock_outs(
    dvc_lock: dict,
    owner_name: str,
    project_name: str,
    get_sizes: bool = False,
    fs=None,
) -> dict:
    """Expand all outs in a DVC lock file.

    Will only pick up those in cloud storage, i.e., not ones that are
    committed to Git.

    Output dictionary structure will look like:

        {
            "figures/plot.png": {
                "path": "figures/plot.png",
                "hash": "md5",
                "md5": "d4cd33821c032be468a77d65873937bc",
                "size": 43613,
            },
            "data/raw": {
                "path": "data/raw",
                "hash": "md5",
                "md5": "d0b6bbbdd9a3dcd765978cda2c754fe7.dir",
                "size": 55354,
                "nfiles": 2,
                "children": [
                    "data/raw/file1.h5...
                ]
            },
            "data/raw/file1.h5": {
                "path": "data/raw/file1.h5",
                "md5": "c3dddc7bf94809e09559b0ae327037f7",
            },
            "data/raw/file2.h5": {
                "path": "data/raw/file2.h5",
                "md5": "d3dddc7bf94809e09669b0ae327037f7",
            }
        }

    """
    if fs is None:
        fs = get_object_fs()
    stages = dvc_lock.get("stages", {})
    dvc_lock_outs = {}
    # Collect all unique .dir md5s upfront, along with the "modern" (non-
    # legacy) object-storage path candidate for each. We read these in
    # parallel; a separate parallel pass falls back to legacy paths only
    # for md5s whose modern path is missing, so we never pay the serial
    # 2x-fs.exists cost per directory that `get_data_fpath_for_md5` used to.
    dir_md5s: set[str] = set()
    for stage_name, stage in stages.items():
        for out in stage.get("outs", []):
            md5 = out.get("md5", "")
            if md5 and md5.endswith(".dir"):
                dir_md5s.add(md5)
    md5_to_candidate: dict[str, str] = {
        md5: make_data_fpath(
            owner_name=owner_name,
            project_name=project_name,
            idx=md5[:2],
            md5=md5[2:],
            legacy=False,
        )
        for md5 in dir_md5s
    }
    md5_to_legacy: dict[str, str] = {
        md5: make_data_fpath(
            owner_name=owner_name,
            project_name=project_name,
            idx=md5[:2],
            md5=md5[2:],
            legacy=True,
        )
        for md5 in dir_md5s
    }

    def _try_read(path: str) -> list[dict] | None:
        try:
            return _read_dvc_dir_cached(path)
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")
            return None

    md5_to_contents: dict[str, list[dict]] = {}
    if dir_md5s:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(_try_read, md5_to_candidate.values()))
        for md5, contents in zip(md5_to_candidate.keys(), results):
            if contents is not None:
                md5_to_contents[md5] = contents
        missing = [md5 for md5 in dir_md5s if md5 not in md5_to_contents]
        if missing:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=10
            ) as executor:
                legacy_results = list(
                    executor.map(
                        _try_read, (md5_to_legacy[md5] for md5 in missing)
                    )
                )
            for md5, contents in zip(missing, legacy_results):
                if contents is not None:
                    md5_to_contents[md5] = contents
    dvc_md5_sizes: dict[str, int | None] = {}
    md5_to_data_fpath: dict[str, str | None] = {}

    def _resolve_data_fpath(md5: str) -> str | None:
        if md5 in md5_to_data_fpath:
            return md5_to_data_fpath[md5]
        resolved = get_data_fpath_for_md5(
            owner_name=owner_name,
            project_name=project_name,
            md5=md5,
            fs=fs,
        )
        md5_to_data_fpath[md5] = resolved
        return resolved

    for stage_name, stage in stages.items():
        for out in stage.get("outs", []):
            outpath = out["path"]
            md5 = out.get("md5", "")
            # If this is a directory, try to fetch its file from cloud storage
            # so we can read off all of the sub-outs
            if md5 and md5.endswith(".dir"):
                if md5 in md5_to_contents:
                    dvc_dir_contents = md5_to_contents[md5]
                    dvc_lock_outs[outpath] = out
                    dvc_lock_outs[outpath]["dirname"] = os.path.dirname(
                        outpath
                    )
                    dvc_lock_outs[outpath]["type"] = "dir"
                    dvc_lock_outs[outpath]["stage"] = stage_name
                    if "children" not in dvc_lock_outs[outpath]:
                        dvc_lock_outs[outpath]["children"] = []
                    # Handle the fact that DVC relpaths could actually be in
                    # subdirectories, so we need to also ensure these subdirs
                    # make it
                    # TODO: This only works one level deep--should be recursive
                    for dvc_obj in dvc_dir_contents:
                        relpath = dvc_obj["relpath"]
                        fname = os.path.basename(relpath)
                        subdir = os.path.dirname(relpath)
                        md5 = dvc_obj.get("md5")
                        if get_sizes and md5 not in dvc_md5_sizes:
                            fpath_i = _resolve_data_fpath(md5)
                            if fpath_i is None:
                                dvc_md5_sizes[md5] = None
                                continue
                            try:
                                size = fs.size(fpath_i)
                            except Exception as e:
                                logger.warning(
                                    f"Failed to get size for {fpath_i}: {e}"
                                )
                            dvc_md5_sizes[md5] = size
                        if subdir:
                            subdir_full_relpath = os.path.join(outpath, subdir)
                            if subdir_full_relpath not in dvc_lock_outs:
                                dvc_lock_outs[subdir_full_relpath] = dict(
                                    type="dir",
                                    children=[],
                                    dirname=outpath,
                                    stage=stage_name,
                                )
                            dvc_lock_outs[subdir_full_relpath][
                                "children"
                            ].append(
                                dict(
                                    relpath=fname,
                                    md5=md5,
                                    type="file",
                                    dirname=subdir_full_relpath,
                                    stage=stage_name,
                                    size=dvc_md5_sizes.get(md5),
                                )
                            )
                            if (
                                subdir_full_relpath
                                not in dvc_lock_outs[outpath]["children"]
                            ):
                                dvc_lock_outs[outpath]["children"].append(
                                    dict(
                                        relpath=subdir,
                                        type="dir",
                                        stage=stage_name,
                                        dirname=outpath,
                                    )
                                )
                        else:
                            subdir_full_relpath = outpath
                        full_relpath = os.path.join(outpath, relpath)
                        dvc_lock_outs[full_relpath] = dvc_obj | dict(
                            dirname=subdir_full_relpath,
                            type="file",
                            stage=stage_name,
                            relpath=fname,
                            path=full_relpath,
                            size=dvc_md5_sizes.get(md5),
                        )
            else:
                dvc_lock_outs[outpath] = out | dict(
                    dirname=os.path.dirname(outpath),
                    type="file",
                    stage=stage_name,
                )
    return dvc_lock_outs
