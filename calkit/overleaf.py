"""Functionality for working with Overleaf."""

import json
import os
import shutil
import subprocess
import tempfile
import warnings
from copy import deepcopy
from functools import cached_property
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
        return (
            Path(tempfile.gettempdir()) / "overleaf" / project_id
        ).as_posix()
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
            overleaf_sync_for_ck_info[synced_dir] = info_in_ck
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
        last_sync_commit: str | None = None,
    ) -> None:
        self.main_repo = main_repo
        self.overleaf_repo = overleaf_repo
        self.path_in_project = path_in_project
        self.sync_info_for_path = deepcopy(sync_info_for_path)
        self.sync_paths_from_config = sync_info_for_path.get("sync_paths", [])
        self.push_paths_from_config = sync_info_for_path.get("push_paths", [])
        self.last_sync_commit = last_sync_commit

    @property
    def push_paths(self) -> list[str]:
        """These paths we only push to Overleaf.

        They are relative to ``{main_repo_dir}/{path_in_project}``.
        """
        return [
            Path(p).as_posix().rstrip("/") for p in self.push_paths_from_config
        ]

    @staticmethod
    def _path_matches(path_posix: str, patterns: list[str]) -> bool:
        """Whether ``path_posix`` equals or lives under any of ``patterns``.

        Patterns are treated as either files or directory prefixes.
        """
        for p in patterns:
            if path_posix == p or path_posix.startswith(p.rstrip("/") + "/"):
                return True
        return False

    def _rel_under_folder(self, paths: list[str]) -> set[str]:
        """Filter ``paths`` (relative to the main repo) to those under the
        synced folder, returning them relative to ``path_in_project``.
        """
        prefix = Path(self.path_in_project).as_posix().rstrip("/")
        prefix_slash = (prefix + "/") if prefix else ""
        res = set()
        for p in paths:
            pp = Path(p).as_posix()
            if prefix_slash:
                if not pp.startswith(prefix_slash):
                    continue
                pp = pp[len(prefix_slash) :]
            if pp:
                res.add(pp)
        return res

    @cached_property
    def stored_files(self) -> set[str]:
        """Files within the synced folder that are "stored", relative to
        ``path_in_project``.

        A file is stored if it is tracked by Git or cached by DVC (i.e., it
        has ``storage`` of ``git`` or ``dvc``). Only stored files are synced
        with Overleaf. Files that are ignored, untracked, or DVC pipeline
        outputs with no storage (``storage: null``) are treated as ignored
        and left out of the sync.
        """
        git_tracked = self._rel_under_folder(
            calkit.git.ls_files(self.main_repo)
        )
        return git_tracked | self.dvc_files

    @cached_property
    def pipeline_output_paths(self) -> set[str]:
        """All DVC pipeline output paths within the synced folder, regardless
        of storage (including uncached ``storage: null`` outputs), relative to
        ``path_in_project``.

        These may be individual files or directories. Any such path that is
        not stored is treated as ignored for syncing -- never pushed to,
        pulled from, or deleted from Overleaf -- since it is generated by the
        pipeline rather than authored.
        """
        try:
            import calkit.dvc

            pipeline = calkit.dvc.read_pipeline(
                wdir=str(self.main_repo.working_dir)
            )
        except Exception as e:
            warnings.warn(f"Could not read pipeline: {e}")
            return set()
        out_paths = []
        for stage in pipeline.get("stages", {}).values():
            if isinstance(stage, dict):
                out_paths.extend(calkit.dvc.out_paths_from_stage(stage))
        return self._rel_under_folder(out_paths)

    def _is_ignored_for_sync(self, rel_posix: str) -> bool:
        """Whether a path (relative to ``path_in_project``) should be treated
        as ignored, and therefore neither synced to/from nor deleted from
        Overleaf.

        A path is ignored if it is gitignored in the main repo, or if it is a
        DVC pipeline output with no storage (``storage: null``). Stored files
        (tracked by Git or cached by DVC) are never ignored, even if they live
        under a pipeline output directory.
        """
        if self.main_repo.ignored(
            os.path.join(self.path_in_project, rel_posix)
        ):
            return True
        if rel_posix in self.stored_files:
            return False
        # A pipeline output that is not stored has storage: null
        return self._path_matches(
            rel_posix, sorted(self.pipeline_output_paths)
        )

    @cached_property
    def files_to_copy_from_overleaf(self) -> list[str]:
        """Return Overleaf files to copy into the main repo.

        We copy all files from Overleaf unless they are in push-only paths
        or are ignored in the main repo. This method does not itself apply
        any special handling for files that were deleted locally since the
        last sync; such deletions are handled elsewhere in the sync logic.
        """
        all_ol_files = calkit.git.ls_files(self.overleaf_repo)
        res = []
        for fpath in all_ol_files:
            fpath_posix = Path(fpath).as_posix()
            # Skip anything ignored for syncing (gitignored or a storage: null
            # pipeline output)
            if self._is_ignored_for_sync(fpath_posix):
                continue
            # Skip files that are under any push-only path
            if self._path_matches(fpath_posix, self.push_paths):
                continue
            res.append(fpath_posix)
        return res

    @cached_property
    def files_to_copy_to_overleaf(self) -> list[str]:
        """Stored files to copy to Overleaf.

        We copy all stored files (tracked by Git or cached by DVC) within the
        synced folder except for private (dot) files, the main PDF, and LaTeX
        aux/build artifacts. Ignored, untracked, and ``storage: null`` files
        are treated as ignored and never pushed.

        These files are all relative to the path in the project.
        """
        root = os.path.join(self.main_repo.working_dir, self.path_in_project)
        # Determine main PDF name (prefer main.tex if present at root)
        main_stem: str | None = None
        main_tex_path = os.path.join(root, "main.tex")
        if os.path.isfile(main_tex_path):
            main_stem = "main"
        elif os.path.isdir(root):
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
            ".auxlock",
        }
        # Multi-part extension handled via endswith
        aux_endswith = (".synctex.gz",)

        def has_hidden_component(rel_path: str) -> bool:
            parts = Path(rel_path).parts
            return any(p.startswith(".") for p in parts)

        results: list[str] = []
        for rel_posix in sorted(self.stored_files):
            # Skip hidden (dot) files and directories
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
            # Only push files that are materialized on disk; stored files that
            # haven't been pulled (e.g., DVC-tracked but not fetched) are kept
            # on Overleaf but cannot be copied
            if not os.path.isfile(os.path.join(root, rel_posix)):
                continue
            results.append(rel_posix)
        return results

    @property
    def paths_to_use_for_git_patch(self) -> list[str]:
        """This should be anything in the Overleaf repo that isn't ignored
        or part of push paths in the main repo.
        """
        return self.files_to_copy_from_overleaf

    @cached_property
    def all_synced_files(self) -> list[str]:
        return list(
            set(
                self.files_to_copy_to_overleaf
                + self.files_to_copy_from_overleaf
            )
        )

    @cached_property
    def files_in_overleaf_last_sync(self) -> set[str]:
        """Files that existed on Overleaf at the last sync commit."""
        files = set()
        if self.last_sync_commit:
            try:
                commit_obj = self.overleaf_repo.commit(self.last_sync_commit)
                files = set(
                    self.overleaf_repo.git.ls_tree(
                        "-r", "--name-only", commit_obj.hexsha
                    ).split("\n")
                )
                files.discard("")
            except (git.BadName, git.GitCommandError, ValueError) as e:
                warnings.warn(
                    f"Could not determine files at last Overleaf sync commit "
                    f"'{self.last_sync_commit}'; proceeding without stale file "
                    f"information. Underlying error: {e}"
                )
        return files

    @cached_property
    def newly_added_on_overleaf(self) -> set[str]:
        """Files that were added on Overleaf since the last sync."""
        return (
            set(self.files_to_copy_from_overleaf)
            - self.files_in_overleaf_last_sync
        )

    @cached_property
    def dvc_files(self) -> set[str]:
        """Files tracked by DVC within the Overleaf project folder.

        These paths are relative to the project directory (i.e., relative to
        the Overleaf repo root). Files tracked by DVC may not exist on disk if
        they haven't been pulled, but should still be kept on Overleaf rather
        than deleted.
        """
        try:
            import calkit.dvc

            dvc_paths = calkit.dvc.list_paths(
                wdir=str(self.main_repo.working_dir), recursive=True
            )
        except Exception as e:
            warnings.warn(f"Could not list DVC files: {e}")
            return set()
        prefix = Path(self.path_in_project).as_posix().rstrip("/") + "/"
        result = set()
        for p in dvc_paths:
            p_posix = Path(p).as_posix()
            if p_posix.startswith(prefix):
                result.add(p_posix[len(prefix) :])
        return result

    @cached_property
    def files_to_keep_on_overleaf(self) -> set[str]:
        """Files preserved on Overleaf, i.e., those that existed at the last
        sync and should not be deleted.

        A file from the last sync is kept if it is still stored locally
        (tracked by Git or cached by DVC), was newly added on Overleaf since
        the last sync, or is treated as ignored (gitignored or a
        ``storage: null`` pipeline output). Only files that were genuinely
        removed from the project are deleted from Overleaf.
        """
        keep = set()
        for f in self.files_in_overleaf_last_sync:
            if (
                f in self.stored_files
                or f in self.newly_added_on_overleaf
                or self._is_ignored_for_sync(f)
            ):
                keep.add(f)
        return keep

    @cached_property
    def stale_files_in_overleaf(self) -> list[str]:
        """Files that existed in the last sync but should be deleted.

        These are stored files that were genuinely removed from the project
        (not merely absent from disk or ignored).
        """
        return sorted(
            self.files_in_overleaf_last_sync - self.files_to_keep_on_overleaf
        )


def get_commits_since_last_sync(
    overleaf_repo: git.Repo, last_sync_commit: str | None
) -> list[git.Commit]:
    if last_sync_commit:
        return list(
            overleaf_repo.iter_commits(rev=f"{last_sync_commit}..HEAD")
        )
    else:
        return []


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
    push_only: bool = False,
) -> dict:
    """Sync between the main project repo and Overleaf repo.

    Both must be up-to-date (pulled). The synced path in the main repo must
    also have no uncommitted changes, since incoming Overleaf edits are
    applied with ``git am``, which refuses to run against a dirty working
    tree (the calling CLI enforces this, optionally committing first with
    ``--auto-commit``).

    Only "stored" files in the main project -- those tracked by Git or cached
    by DVC -- are synced. They are synced bidirectionally, except for files
    under ``push_paths``, which are only pushed to Overleaf. Files that are
    ignored, untracked, or DVC pipeline outputs with no storage
    (``storage: null``, e.g., LaTeX build artifacts) are treated as ignored:
    they are never pushed to, pulled from, or deleted from Overleaf. A file is
    only deleted from Overleaf when a previously-synced stored file is
    genuinely removed from the project.

    When push_only is True, only push local files to Overleaf without pulling
    or applying changes from Overleaf to local. Useful for initializing a new
    Overleaf project from local files.

    When no_commit is True, changes are still pulled from Overleaf and pushed
    to Overleaf, but no commit is created in the main project repo; the pulled
    changes are left staged instead. Overleaf changes are applied with
    ``git am``, which necessarily creates commits, so those commits are undone
    with a soft reset back to ``project_commit_before`` (which keeps their
    changes staged). See the ``--no-commit`` handling near the end of this
    function.
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
    res["commits_since_last_sync"] = get_commits_since_last_sync(
        overleaf_repo=overleaf_repo, last_sync_commit=last_sync_commit
    )
    res["project_commit_before"] = main_repo.head.commit.hexsha
    res["overleaf_commit_before"] = overleaf_repo.head.commit.hexsha
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
        last_sync_commit=last_sync_commit,
    )
    paths_for_overleaf_patch = paths.paths_to_use_for_git_patch
    res["paths_for_overleaf_patch"] = paths_for_overleaf_patch
    if push_only:
        # When push_only is True, skip pulling from Overleaf and applying
        # patches to local
        # Simply copy files to Overleaf
        print_info("Push-only sync; skipping pull from Overleaf")
        res["patch"] = None
    elif last_sync_commit:
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
        res["patch"] = patch
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
            if process.returncode != 0 and (
                "merge conflict" in process.stdout.lower()
                or "merge conflict" in process.stderr.lower()
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
                main_repo.git.am("--abort")
                raise RuntimeError(
                    "Could not apply Git patch:\n"
                    f"{process.stdout}\n{process.stderr}"
                )
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
        res["patch"] = None
        files_to_copy_from_overleaf = paths.files_to_copy_from_overleaf
        res["files_to_copy_from_overleaf"] = files_to_copy_from_overleaf
        for sync_path in files_to_copy_from_overleaf:
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
    res["files_to_copy_to_overleaf"] = files_to_copy_to_overleaf
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
        else:
            raise RuntimeError(
                f"Source path {src} does not exist; "
                "please check your Overleaf config"
            )
    # Delete stale files from Overleaf (files that existed before but are
    # no longer locally or have been excluded from sync)
    res["newly_added_on_overleaf"] = sorted(paths.newly_added_on_overleaf)
    res["files_to_keep_on_overleaf"] = sorted(paths.files_to_keep_on_overleaf)
    res["stale_files_in_overleaf"] = paths.stale_files_in_overleaf
    for stale_path in paths.stale_files_in_overleaf:
        file_path = os.path.join(overleaf_project_dir_abs, stale_path)
        if os.path.isfile(file_path):
            os.remove(file_path)
    # Stage the changes in the Overleaf project
    res["committed_overleaf"] = False
    overleaf_repo.git.add(".")
    if overleaf_repo.git.diff("--staged"):
        print_info("Committing changes to Overleaf")
        commit_message = "Sync with Calkit project"
        overleaf_repo.git.commit("-m", commit_message)
        print_info("Pushing changes to Overleaf")
        overleaf_repo.git.push()
        res["committed_overleaf"] = True
    # Update the last sync commit
    last_overleaf_commit = overleaf_repo.head.commit.hexsha
    res["overleaf_commit_after"] = last_overleaf_commit
    if res["committed_overleaf"]:
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
    # Auto-ignore any untracked build artifacts (e.g., LaTeX aux files like
    # .auxlock) in the synced folder so they don't get committed during sync
    gitignore_modified = False
    path_prefix = path_in_project.rstrip("/") + "/"
    for untracked in main_repo.untracked_files:
        untracked_posix = Path(untracked).as_posix()
        if not untracked_posix.startswith(path_prefix):
            continue
        if (
            any(
                untracked_posix.endswith(s)
                for s in calkit.AUTO_IGNORE_SUFFIXES
            )
            or any(
                untracked_posix.startswith(p)
                for p in calkit.AUTO_IGNORE_PREFIXES
            )
            or untracked_posix
            in [Path(p).as_posix() for p in calkit.AUTO_IGNORE_PATHS]
        ):
            if calkit.git.ensure_path_is_ignored(main_repo, untracked_posix):
                print_info(f"Automatically ignoring {untracked_posix}")
                main_repo.git.add(".gitignore")
                gitignore_modified = True
    # Stage the changes in the project repo
    res["committed_project"] = False
    main_repo.git.add(path_in_project)
    paths_to_commit = [
        path_in_project,
        "calkit.yaml",
        overleaf_sync_data_fpath,
    ]
    if gitignore_modified:
        paths_to_commit.append(".gitignore")
    staged_diff = main_repo.git.diff(["--staged"] + paths_to_commit)
    if staged_diff and not no_commit:
        print_info("Committing changes to project repo")
        commit_message = f"Sync {path_in_project} with Overleaf project"
        main_repo.git.commit(*paths_to_commit, "-m", commit_message)
        res["committed_project"] = True
    elif no_commit and (
        main_repo.head.commit.hexsha != res["project_commit_before"]
    ):
        # Changes pulled from Overleaf are applied via 'git am', which creates
        # commits in the main repo. Since --no-commit was requested, undo
        # those commits while keeping their changes staged.
        print_info(
            "Resetting commits created while applying Overleaf changes "
            "(leaving them staged)"
        )
        main_repo.git.reset("--soft", res["project_commit_before"])
    res["project_commit_after"] = main_repo.head.commit.hexsha
    return res
