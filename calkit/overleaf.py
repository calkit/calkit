"""Functionality for working with Overleaf."""

import json
import os
import shutil
import subprocess
import warnings
from copy import deepcopy
from pathlib import Path

import git

import calkit

PRIVATE_KEYS = ["project_id", "last_sync_commit"]


def get_git_remote_url(project_id: str, token: str) -> str:
    """Form the Git remote URL for an Overleaf project.

    If running against a test environment, this will use a local directory.
    """
    if calkit.config.get_env() == "test":
        return os.path.join("/tmp", "overleaf", project_id)
    return f"https://git:{token}@git.overleaf.com/{project_id}"


def project_id_to_url(project_id: str) -> str:
    return f"https://www.overleaf.com/project/{project_id}"


def project_id_from_url(url: str) -> str:
    return url.split("/")[-1]


def get_sync_info(
    wdir: str | None = None,
    ck_info: dict | None = None,
    fix_legacy: bool = True,
) -> dict:
    """Load in a dictionary of Overleaf sync data, keyed by path relative to
    ``wdir``.
    """
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    overleaf_info = {}
    # If we have any publications synced with Overleaf, get those and remove
    # from calkit.yaml if desired, since that's legacy behavior
    pubs = ck_info.get("publications", [])
    for pub in pubs:
        if "overleaf" in pub:
            pub_overleaf = pub.pop("overleaf")
            pub_wdir = pub_overleaf.get("wdir")
            if not pub_wdir:
                if "path" not in pub:
                    warnings.warn(f"Publication '{pub}' has no path")
                pub_wdir = os.path.dirname(pub["path"])
            overleaf_info[Path(pub_wdir).as_posix()] = pub_overleaf
    if wdir is None:
        wdir = ""
    info_path = os.path.join(wdir, ".calkit", "overleaf.json")
    if os.path.isfile(info_path):
        with open(info_path) as f:
            ol_info_private = json.load(f)
        for k, v in ol_info_private.items():
            if k not in overleaf_info:
                overleaf_info[k] = {}
            for k1, v1 in v.items():
                overleaf_info[k][k1] = v1
    # Override with any values defined in calkit.yaml
    if "overleaf_sync" in ck_info:
        ol_info_ck = deepcopy(ck_info["overleaf_sync"])
        for k, v in ol_info_ck.items():
            if k not in overleaf_info:
                overleaf_info[k] = {}
            for k1, v1 in v.items():
                overleaf_info[k][k1] = v1
    # Iterate through and fix data if necessary
    for synced_dir, dirinfo in overleaf_info.items():
        if "url" in dirinfo:
            dirinfo["project_id"] = project_id_from_url(dirinfo["url"])
    if fix_legacy:
        overleaf_sync_for_ck_info = ck_info.get("overleaf_sync", {})
        for synced_dir, info in overleaf_info.items():
            info_in_ck = overleaf_sync_for_ck_info.get(synced_dir, {})
            if "url" not in info_in_ck:
                info_in_ck["url"] = project_id_to_url(info["project_id"])
            if "sync_paths" in info:
                info_in_ck["sync_paths"] = info["sync_paths"]
            if "push_paths" in info:
                info_in_ck["push_paths"] = info["push_paths"]
        ck_info["overleaf_sync"] = overleaf_sync_for_ck_info
        with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
            calkit.ryaml.dump(ck_info, f)
        os.makedirs(os.path.join(wdir, ".calkit"), exist_ok=True)
        private_info = {}
        for synced_dir, info in overleaf_info.items():
            private_info[synced_dir] = {k: info.get(k) for k in PRIVATE_KEYS}
        with open(info_path, "w") as f:
            json.dump(private_info, f, indent=2)
    return overleaf_info


def write_sync_info(
    synced_path: str, info: dict, wdir: str | None = None
) -> str:
    """Write sync info for a given path, overwriting the data for that path."""
    # First read in the data
    if wdir is None:
        wdir = ""
    fpath = os.path.join(wdir, ".calkit", "overleaf.json")
    if os.path.isfile(fpath):
        with open(fpath) as f:
            existing = json.load(f)
    else:
        existing = {}
    existing[synced_path] = {k: info.get(k) for k in PRIVATE_KEYS}
    with open(fpath, "w") as f:
        json.dump(existing, f, indent=2)
    return fpath


def sync(
    main_repo: git.Repo,
    overleaf_repo: git.Repo,
    path_in_project: str,
    sync_info_for_path: dict,
    last_sync_commit: str | None = None,
    no_commit: bool = False,
    print_info=print,
    warn=warnings.warn,
    verbose: bool = False,
    resolve: bool = False,
) -> dict:
    """Sync between the main project repo and Overleaf repo.

    Both must be up-to-date (pulled).
    """
    res = {}
    abs_synced_path_in_project = os.path.join(
        main_repo.working_dir, path_in_project
    )
    overleaf_project_dir = overleaf_repo.working_dir
    # Determine which paths to sync and push
    overleaf_sync_data = deepcopy(sync_info_for_path)
    git_sync_paths = deepcopy(overleaf_sync_data.get("sync_paths", []))
    git_sync_paths += overleaf_sync_data.get("git_sync_paths", [])
    sync_paths = git_sync_paths
    push_paths = deepcopy(overleaf_sync_data.get("push_paths", []))
    # TODO: Duplication here in conflict fpath
    conflict_fpath = os.path.join(
        main_repo.working_dir, ".calkit", "overleaf", "CONFLICT.json"
    )
    implicit_sync_paths = os.listdir(overleaf_repo.working_dir)
    for p in implicit_sync_paths:
        if p.startswith("."):
            continue
        if p not in sync_paths:
            sync_paths.append(p)
            if p not in git_sync_paths:
                git_sync_paths.append(p)
    # Add implicit sync paths in project
    paths_in_project = os.listdir(abs_synced_path_in_project)
    for p in paths_in_project:
        if p.startswith(".") or p.endswith(".pdf"):
            continue
        if p not in sync_paths:
            sync_paths.append(p)
        if p not in git_sync_paths:
            git_sync_paths.append(p)
    git_sync_paths_in_project = [
        os.path.join(path_in_project, p) for p in git_sync_paths
    ]
    if not sync_paths:
        warn("No sync paths defined in Overleaf config")
    elif last_sync_commit:
        # Compute a patch in the Overleaf project between HEAD and the last
        # sync
        patch = overleaf_repo.git.format_patch(
            [f"{last_sync_commit}..HEAD", "--stdout", "--"] + git_sync_paths
        )
        # Replace any Overleaf commit messages to make them more meaningful
        patch = patch.replace(
            "Update on Overleaf.", f"Update {path_in_project} on Overleaf"
        )
        # Ensure the patch ends with a new line
        if patch and not patch.endswith("\n"):
            patch += "\n"
        if verbose:
            print_info(f"Git patch:\n{patch}")
        if patch:
            print_info("Applying to project repo")
            process = subprocess.run(
                [
                    "git",
                    "am",
                    "--3way",
                    "--directory",
                    path_in_project,
                    "-",
                ],
                input=patch,
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=main_repo.working_dir,
            )
            # Handle merge conflicts
            if (
                process.returncode != 0
                and "merge conflict" in process.stdout.lower()
            ):
                msg = ""
                for line in process.stdout.split("\n"):
                    if "merge conflict" in line.lower():
                        msg += line + "\n"
                # Save a file to track this merge conflict
                c = overleaf_repo.head.commit.hexsha
                with open(conflict_fpath, "w") as f:
                    json.dump(
                        {
                            "wdir": path_in_project,
                            "last_overleaf_commit": c,
                        },
                        f,
                    )
                raise RuntimeError(
                    f"{msg}Edit the file(s) and then call:\n\n"
                    "    calkit overleaf sync --resolve"
                )
            elif process.returncode != 0:
                raise RuntimeError(f"Could not apply:\n{process.stdout}")
        elif resolve:
            # We have no patch since the last sync, but we need to update
            # our latest sync commit
            print_info("Merge conflict resolved")
        else:
            print_info("No changes to apply")
    else:
        # Simply copy in all files
        print_info(
            "No last sync commit defined; "
            "copying all files from Overleaf project"
        )
        for sync_path in sync_paths:
            src = os.path.join(overleaf_project_dir, sync_path)
            dst = os.path.join(abs_synced_path_in_project, sync_path)
            if os.path.isdir(src):
                # Copy the directory and its contents
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                # Copy the file
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            else:
                raise RuntimeError(
                    f"Source path {src} does not exist; "
                    "please check your Overleaf config"
                )
    # Copy our versions of sync and push paths into the Overleaf project
    for sync_push_path in sync_paths + push_paths:
        src = os.path.join(abs_synced_path_in_project, sync_push_path)
        dst = os.path.join(overleaf_project_dir, sync_push_path)
        if os.path.isdir(src):
            # Remove destination directory if it exists
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            # Copy the directory and its contents
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif os.path.isfile(src):
            # Copy the file
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        elif os.path.isfile(dst) and not os.path.isfile(src):
            # Handle newly created files on Overleaf, i.e., they exist
            # in dst but not in src
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.copy2(dst, src)
        else:
            raise RuntimeError(
                f"Source path {src} does not exist; "
                "please check your Overleaf config"
            )
            continue
    # Stage the changes in the Overleaf project
    overleaf_repo.git.add(sync_paths + push_paths)
    if overleaf_repo.git.diff("--staged", sync_paths + push_paths):
        print_info("Committing changes to Overleaf")
        commit_message = "Sync with Calkit project"
        overleaf_repo.git.commit(
            *(sync_paths + push_paths),
            "-m",
            commit_message,
        )
        print_info("Pushing changes to Overleaf")
        overleaf_repo.git.push()
    # Update the last sync commit
    last_overleaf_commit = overleaf_repo.head.commit.hexsha
    print_info(f"Updating last sync commit as {last_overleaf_commit}")
    overleaf_sync_data["last_sync_commit"] = last_overleaf_commit
    # Write Overleaf sync data
    overleaf_sync_data_fpath = write_sync_info(
        synced_path=path_in_project,
        info=overleaf_sync_data,
        wdir=str(main_repo.working_dir),
    )
    main_repo.git.add("calkit.yaml")
    main_repo.git.add(overleaf_sync_data_fpath)
    if resolve and os.path.isfile(conflict_fpath):
        os.remove(conflict_fpath)
    # Stage the changes in the project repo
    # Respect any sync paths that are ignored by Git
    git_sync_paths_in_project_not_ignored = [
        p for p in git_sync_paths_in_project if not main_repo.ignored(p)
    ]
    main_repo.git.add(git_sync_paths_in_project_not_ignored)
    if (
        main_repo.git.diff(
            "--staged",
            git_sync_paths_in_project_not_ignored
            + ["calkit.yaml", overleaf_sync_data_fpath],
        )
        and not no_commit
    ):
        print_info("Committing changes to project repo")
        commit_message = f"Sync {path_in_project} with Overleaf project"
        main_repo.git.commit(
            *(
                git_sync_paths_in_project_not_ignored
                + ["calkit.yaml", overleaf_sync_data_fpath]
            ),
            "-m",
            commit_message,
        )
    return res
