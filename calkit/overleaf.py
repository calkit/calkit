"""Functionality for working with Overleaf."""

import json
import os
import shutil
import subprocess
import warnings
from copy import deepcopy
from os import PathLike
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
    wdir: str | PathLike | None = None,
    ck_info: dict | None = None,
    fix_legacy: bool = False,
) -> dict:
    """Load in a dictionary of Overleaf sync data, keyed by path relative to
    ``wdir`` (the project working directory).
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
    info_path = get_sync_info_fpath(wdir=wdir)
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


def get_sync_info_fpath(wdir: str | PathLike | None = None) -> str:
    if wdir is None:
        wdir = ""
    return os.path.join(wdir, ".calkit", "overleaf-sync.json")


def write_sync_info(
    synced_path: str, info: dict, wdir: str | PathLike | None = None
) -> str:
    """Write sync info for a given path, overwriting the data for that path."""
    # First read in the data
    if wdir is None:
        wdir = ""
    fpath = get_sync_info_fpath(wdir=wdir)
    if os.path.isfile(fpath):
        with open(fpath) as f:
            existing = json.load(f)
    else:
        existing = {}
    synced_path = Path(synced_path).as_posix()
    existing[synced_path] = {k: info.get(k) for k in PRIVATE_KEYS}
    with open(fpath, "w") as f:
        json.dump(existing, f, indent=2)
    return fpath


def get_conflict_fpath(wdir: str | PathLike | None = None) -> str:
    if wdir is None:
        wdir = ""
    return os.path.join(str(wdir), ".calkit", "overleaf", "CONFLICT.json")


class OverleafSyncPaths:
    def __init__(
        self,
        main_repo: git.Repo,
        overleaf_repo: git.Repo,
        path_in_project: str,
        sync_info_for_path: dict,
    ) -> None:
        self.main_repo = main_repo
        self.overleaf_repo = overleaf_repo
        self.path_in_project = path_in_project
        self.sync_info_for_path = deepcopy(sync_info_for_path)
        self.sync_paths_from_config = sync_info_for_path.get("sync_paths", [])
        self.push_paths_from_config = sync_info_for_path.get("push_paths", [])

    @property
    def push_paths(self) -> list[str]:
        """These paths we only push to Overleaf.

        They are relative to ``{main_repo_dir}/{path_in_project}``.
        """
        return self.push_paths_from_config

    @property
    def files_to_copy_from_overleaf(self) -> list[str]:
        """We basically copy all files from Overleaf unless they are in
        push paths or ignored in the main repo.
        """
        all_ol_files = calkit.git.ls_files(self.overleaf_repo)
        # Normalize push paths (treat both files and directories)
        push_paths = [
            Path(p).as_posix().rstrip("/") for p in self.push_paths_from_config
        ]
        res = []
        for fpath in all_ol_files:
            fpath_posix = Path(fpath).as_posix()
            relpath_main = os.path.join(self.path_in_project, fpath_posix)
            # Skip anything ignored in main repo
            if self.main_repo.ignored(relpath_main):
                continue
            # Skip files that are under any push-only path
            in_push_path = False
            for p in push_paths:
                if fpath_posix == p or fpath_posix.startswith(p + "/"):
                    in_push_path = True
                    break
            if in_push_path:
                continue
            res.append(fpath_posix)
        return res

    @property
    def files_to_copy_to_overleaf(self) -> list[str]:
        """We should basically copy all files to Overleaf except for
        private (dot) files, the main PDF, and aux files.

        These files should all be relative to the path in the project.
        """
        root = os.path.join(self.main_repo.working_dir, self.path_in_project)
        if not os.path.isdir(root):
            return []
        # Determine main PDF name (prefer main.tex if present at root)
        main_stem: str | None = None
        main_tex_path = os.path.join(root, "main.tex")
        if os.path.isfile(main_tex_path):
            main_stem = "main"
        else:
            # Fallback: if there is exactly one top-level .tex file, use it
            top_level_files = [
                f
                for f in os.listdir(root)
                if os.path.isfile(os.path.join(root, f))
            ]
            root_tex = [f for f in top_level_files if f.endswith(".tex")]
            if len(root_tex) == 1:
                main_stem = Path(root_tex[0]).stem
        main_pdf_rel = None
        if main_stem is not None:
            main_pdf_rel = Path(f"{main_stem}.pdf").as_posix()
        # Common LaTeX aux/build artifacts to exclude
        aux_suffixes = {
            ".aux",
            ".log",
            ".out",
            ".toc",
            ".bbl",
            ".blg",
            ".fls",
            ".fdb_latexmk",
            ".lof",
            ".lot",
            ".lol",
            ".nav",
            ".snm",
            ".vrb",
            ".dvi",
            ".xdv",
        }
        # Multi-part extension handled via endswith
        aux_endswith = (".synctex.gz",)

        def has_hidden_component(rel_path: str) -> bool:
            parts = Path(rel_path).parts
            return any(p.startswith(".") for p in parts)

        results: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden directories early
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fname in filenames:
                # Skip hidden files
                if fname.startswith("."):
                    continue
                f_abs = os.path.join(dirpath, fname)
                rel = os.path.relpath(f_abs, root)
                rel_posix = Path(rel).as_posix()
                if has_hidden_component(rel_posix):
                    continue
                # Skip main PDF specifically
                if main_pdf_rel is not None and rel_posix == main_pdf_rel:
                    continue
                # Skip LaTeX aux/build artifacts
                if (
                    rel_posix.endswith(aux_endswith)
                    or Path(rel_posix).suffix in aux_suffixes
                ):
                    continue
                results.append(rel_posix)
        return results

    @property
    def paths_to_use_for_git_patch(self) -> list[str]:
        """This should be anything in the Overleaf repo that isn't ignored
        or part of push paths in the main repo.
        """
        return self.files_to_copy_from_overleaf

    @property
    def all_synced_files(self) -> list[str]:
        return list(
            set(
                self.files_to_copy_to_overleaf
                + self.files_to_copy_from_overleaf
            )
        )


def sync(
    main_repo: git.Repo,
    overleaf_repo: git.Repo,
    path_in_project: str,
    sync_info_for_path: dict | None = None,
    last_sync_commit: str | None = None,
    no_commit: bool = False,
    print_info=print,
    verbose: bool = False,
    resolving_conflict: bool = False,
) -> dict:
    """Sync between the main project repo and Overleaf repo.

    Both must be up-to-date (pulled).

    All files in the Overleaf repo are committed to Git, while some in the
    main project can be ignored, e.g., in cases where they are copied in from
    a map-paths stage.
    """
    res = {}
    # Normalize ``path_in_project`` as a posix path
    path_in_project = Path(path_in_project).as_posix()
    if sync_info_for_path is None:
        sync_info_for_path = get_sync_info(
            wdir=main_repo.working_dir, fix_legacy=True
        ).get(path_in_project, {})
    assert isinstance(sync_info_for_path, dict)
    if last_sync_commit is None:
        last_sync_commit = sync_info_for_path.get("last_sync_commit")
    path_in_project_abs = os.path.join(main_repo.working_dir, path_in_project)
    overleaf_project_dir_abs = overleaf_repo.working_dir
    conflict_fpath = get_conflict_fpath(wdir=main_repo.working_dir)
    # Determine which paths to sync and push
    overleaf_sync_data = deepcopy(sync_info_for_path)
    paths = OverleafSyncPaths(
        main_repo=main_repo,
        overleaf_repo=overleaf_repo,
        path_in_project=path_in_project,
        sync_info_for_path=sync_info_for_path,
    )
    paths_for_overleaf_patch = paths.paths_to_use_for_git_patch
    if last_sync_commit:
        # Compute a patch in the Overleaf project between HEAD and the last
        # sync
        patch = overleaf_repo.git.format_patch(
            [f"{last_sync_commit}..HEAD", "--stdout", "--"]
            + paths_for_overleaf_patch
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
        elif resolving_conflict:
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
        for sync_path in paths.files_to_copy_from_overleaf:
            src = os.path.join(overleaf_project_dir_abs, sync_path)
            dst = os.path.join(path_in_project_abs, sync_path)
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
    files_to_copy_to_overleaf = paths.files_to_copy_to_overleaf
    if verbose:
        print_info(
            f"Copying the following files to Overleaf: "
            f"{files_to_copy_to_overleaf}"
        )
    for sync_push_path in files_to_copy_to_overleaf:
        src = os.path.join(path_in_project_abs, sync_push_path)
        dst = os.path.join(overleaf_project_dir_abs, sync_push_path)
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
    # Stage the changes in the Overleaf project
    overleaf_repo.git.add(".")
    if overleaf_repo.git.diff("--staged"):
        print_info("Committing changes to Overleaf")
        commit_message = "Sync with Calkit project"
        overleaf_repo.git.commit("-m", commit_message)
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
    if resolving_conflict and os.path.isfile(conflict_fpath):
        os.remove(conflict_fpath)
    # Stage the changes in the project repo
    main_repo.git.add(path_in_project)
    if (
        main_repo.git.diff(
            [
                "--staged",
                path_in_project,
                "calkit.yaml",
                overleaf_sync_data_fpath,
            ],
        )
        and not no_commit
    ):
        print_info("Committing changes to project repo")
        commit_message = f"Sync {path_in_project} with Overleaf project"
        main_repo.git.commit(
            path_in_project,
            "calkit.yaml",
            overleaf_sync_data_fpath,
            "-m",
            commit_message,
        )
    return res
