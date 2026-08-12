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


# Git config options that force authentication to use only the token embedded
# in the Overleaf remote URL, never a credential saved in the operating
# system's credential store (macOS Keychain, Windows Credential Manager, etc.).
# An expired token can linger in that store and shadow a freshly set one, which
# otherwise makes it impossible to recover a project after a token expires.
_CREDENTIAL_CLONE_OPTIONS = [
    "-c credential.helper=",
    "-c credential.interactive=false",
]


def _disable_credential_store(repo: git.Repo) -> None:
    """Configure a cloned Overleaf repo so git authenticates only with the
    token embedded in its remote URL, ignoring the OS credential store.

    Setting an empty ``credential.helper`` in the repo's local config resets
    the list of helpers inherited from the system and global config, so no
    stale token can be read from (or written to) the credential store.
    """
    repo.git.config("credential.helper", "")
    repo.git.config("credential.interactive", "false")


def get_project_dir(project_id: str) -> str:
    """Return the local directory into which an Overleaf project is cloned,
    relative to the Calkit project working directory.
    """
    return os.path.join(".calkit", "overleaf", project_id)


def clone(project_id: str, token: str) -> git.Repo:
    """Clone an Overleaf project, authenticating only with ``token``."""
    repo = git.Repo.clone_from(
        get_git_remote_url(project_id=project_id, token=token),
        get_project_dir(project_id),
        multi_options=_CREDENTIAL_CLONE_OPTIONS,
        allow_unsafe_options=True,
    )
    _disable_credential_store(repo)
    return repo


def get_repo(project_id: str, token: str) -> git.Repo:
    """Return the Overleaf repo for ``project_id``, cloning it if it does not
    yet exist.

    When the repo already exists, its remote URL is refreshed so a freshly set
    token takes effect, and credential handling is reset so a stale token from
    the OS credential store is never used.
    """
    dest = get_project_dir(project_id)
    if not os.path.isdir(dest):
        return clone(project_id, token)
    repo = calkit.git.get_repo(dest)
    repo.git.remote(
        "set-url",
        "origin",
        get_git_remote_url(project_id=project_id, token=token),
    )
    _disable_credential_store(repo)
    return repo


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
    # A project that has never used Calkit locally has no .calkit directory,
    # which is the normal case on the hub: it writes this into a fresh clone
    # while importing an Overleaf document as a publication
    os.makedirs(os.path.dirname(fpath) or ".", exist_ok=True)
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
    def all_pipeline_output_paths(self) -> set[str]:
        """All DVC pipeline output paths in the project, relative to the main
        repo, regardless of storage (including uncached ``storage: null``
        outputs).

        Kept repo-relative rather than folder-relative because a map-paths
        source usually lives outside the synced folder, and whether it is
        itself generated decides if an Overleaf edit can be sent back to it.
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
        return {Path(p).as_posix() for p in out_paths}

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
        return self._rel_under_folder(sorted(self.all_pipeline_output_paths))

    @cached_property
    def _pipeline_output_path_list(self) -> list[str]:
        """``pipeline_output_paths`` as a sorted list, computed once."""
        return sorted(self.pipeline_output_paths)

    def _is_pipeline_output(self, rel_posix: str) -> bool:
        """Whether a path is produced by the pipeline rather than authored."""
        return self._path_matches(rel_posix, self._pipeline_output_path_list)

    @cached_property
    def _map_paths_mappings(self) -> list:
        """Every mapping of every ``map-paths`` stage in the project.

        Built through the model so each mapping kind's destination is worked
        out the same way the pipeline works it out.
        """
        from calkit.models.pipeline import MapPathsStage

        try:
            ck_info = calkit.load_calkit_info(
                wdir=str(self.main_repo.working_dir)
            )
        except Exception as e:
            warnings.warn(f"Could not read Calkit pipeline: {e}")
            return []
        stages = (ck_info.get("pipeline") or {}).get("stages") or {}
        mappings: list = []
        for stage in stages.values():
            if not isinstance(stage, dict) or stage.get("kind") != "map-paths":
                continue
            try:
                parsed = MapPathsStage(**stage)
            except Exception as e:
                warnings.warn(f"Could not read map-paths stage: {e}")
                continue
            mappings.extend(parsed.paths)
        return mappings

    @cached_property
    def map_paths_outputs(self) -> set[str]:
        """Destinations of ``map-paths`` stages within the synced folder.

        A map-paths stage copies authored files into the document's folder --
        a shared ``references.bib`` or class file used by several papers.
        The copy is a pipeline output with no storage, so nothing else here
        treats it as syncable, but Overleaf needs it to compile the document.
        """
        return self._rel_under_folder(
            [p.out_path for p in self._map_paths_mappings]
        )

    @cached_property
    def map_paths_sources(self) -> dict[str, str]:
        """Map-paths copies in the synced folder, each pointing back at the
        file it was copied from.

        Keys are relative to ``path_in_project``, values relative to the main
        repo. This inverts what a map-paths stage does, so an edit made on
        Overleaf to one of these copies can be written back to the file the
        stage builds it from instead of being discarded -- the copy itself is
        regenerated on the next run, so an edit left there would be lost.

        A source is only included if it is authored: a source that is itself
        produced by another stage would have the edit overwritten just the
        same, so those are left out and reported as unrecoverable.
        """
        generated = self.all_pipeline_output_paths
        # Sources are only ever read here, so a directory mapping is inverted
        # by walking what the source actually contains
        main_dir = str(self.main_repo.working_dir)
        res: dict[str, str] = {}
        for mapping in self._map_paths_mappings:
            src = Path(mapping.src).as_posix()
            pairs: list[tuple[str, str]] = []
            if mapping.kind in ("file-to-file", "file-to-dir"):
                pairs.append((Path(mapping.out_path).as_posix(), src))
            else:
                # dir-to-dir-merge and dir-to-dir-replace: each file keeps its
                # path relative to the source directory
                src_abs = os.path.join(main_dir, src)
                dest = Path(mapping.out_path).as_posix()
                for dirpath, _, filenames in os.walk(src_abs):
                    for name in filenames:
                        rel = Path(
                            os.path.relpath(
                                os.path.join(dirpath, name), src_abs
                            )
                        ).as_posix()
                        pairs.append(
                            (f"{dest}/{rel}", f"{src}/{rel}"),
                        )
            for dest_path, src_path in pairs:
                if self._path_matches(src_path, sorted(generated)):
                    continue
                rel_dest = self._rel_under_folder([dest_path])
                for rel in rel_dest:
                    res[rel] = src_path
        return res

    @cached_property
    def mapped_files(self) -> set[str]:
        """Files on disk under a map-paths destination.

        Relative to ``path_in_project``. A destination may be a single file
        or a whole directory, so directories are walked.
        """
        root = os.path.join(self.main_repo.working_dir, self.path_in_project)
        res: set[str] = set()
        for dest in self.map_paths_outputs:
            abs_dest = os.path.join(root, dest)
            if os.path.isfile(abs_dest):
                res.add(dest)
            elif os.path.isdir(abs_dest):
                for dirpath, _, filenames in os.walk(abs_dest):
                    for name in filenames:
                        abs_file = os.path.join(dirpath, name)
                        res.add(
                            Path(os.path.relpath(abs_file, root)).as_posix()
                        )
        return res

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
        return self._is_pipeline_output(rel_posix)

    @cached_property
    def files_to_copy_from_overleaf(self) -> list[str]:
        """Return Overleaf files to copy into the main repo.

        We copy all files from Overleaf unless they are in push-only paths,
        are produced by the pipeline, or are ignored in the main repo. This
        method does not itself apply any special handling for files that were
        deleted locally since the last sync; such deletions are handled
        elsewhere in the sync logic.
        """
        all_ol_files = calkit.git.ls_files(self.overleaf_repo)
        res = []
        for fpath in all_ol_files:
            fpath_posix = Path(fpath).as_posix()
            # Skip anything ignored for syncing (gitignored or a storage: null
            # pipeline output)
            if self._is_ignored_for_sync(fpath_posix):
                continue
            # Skip anything the pipeline produces, even when it's stored in
            # Git. Pulling an edit into a generated file would look like it
            # worked and then be overwritten by the next run; the edit belongs
            # in whatever the stage builds it from.
            if self._is_pipeline_output(fpath_posix):
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
        synced folder, plus the copies a ``map-paths`` stage puts there,
        except for private (dot) files, the main PDF, and LaTeX aux/build
        artifacts. Other ignored, untracked, and ``storage: null`` files are
        never pushed.

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
        # Map-paths copies are pushed alongside stored files: the content is
        # authored (in the source the stage copies from) and Overleaf can't
        # compile the document without it.
        for rel_posix in sorted(self.stored_files | self.mapped_files):
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
    def pipeline_outputs_changed_on_overleaf(self) -> list[str]:
        """Generated files someone edited on Overleaf since the last sync.

        These edits can't be pulled back -- the next pipeline run would
        overwrite them -- so they're worth saying out loud rather than
        dropping quietly.
        """
        if not self.last_sync_commit:
            return []
        try:
            changed = self.overleaf_repo.git.diff(
                "--name-only", f"{self.last_sync_commit}..HEAD"
            ).split("\n")
        except (git.BadName, git.GitCommandError, ValueError) as e:
            warnings.warn(f"Could not diff the Overleaf repo: {e}")
            return []
        return sorted(
            {
                Path(f).as_posix()
                for f in changed
                if f and self._is_pipeline_output(Path(f).as_posix())
            }
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


FIGURE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".pdf",
    ".eps",
    ".ps",
    ".tif",
    ".tiff",
    ".webp",
}


def get_sync_status(
    main_repo: git.Repo,
    overleaf_repo: git.Repo,
    path_in_project: str,
    sync_info_for_path: dict | None = None,
    last_sync_commit: str | None = None,
    ck_info: dict | None = None,
) -> dict:
    """Compute the sync status between a project and an Overleaf project.

    This is the read-only counterpart to ``sync``: it reports what a sync
    would do without touching either repo. Both repos should already be
    up-to-date (pulled), same as for ``sync``.

    The returned dictionary reports how many commits are waiting on
    Overleaf, which stored files differ from their Overleaf counterparts
    (and would therefore be pushed), and which previously-synced files
    would be deleted from Overleaf. Each file is flagged as a figure or
    not, so callers can surface out-of-date figures specifically.
    """
    path_in_project = Path(path_in_project).as_posix()
    if sync_info_for_path is None:
        sync_info_for_path = get_sync_info(wdir=main_repo.working_dir).get(
            path_in_project, {}
        )
    if last_sync_commit is None:
        last_sync_commit = sync_info_for_path.get("last_sync_commit")
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=main_repo.working_dir)
    # Declared figures are stored relative to the repo root, but sync works
    # relative to the synced folder, so translate them once up front
    prefix = path_in_project.rstrip("/")
    prefix_slash = (prefix + "/") if prefix else ""
    declared_figures = set()
    for fig in ck_info.get("figures") or []:
        fig_path = fig.get("path") if isinstance(fig, dict) else fig
        if not isinstance(fig_path, str):
            continue
        fig_posix = Path(fig_path).as_posix()
        if prefix_slash and not fig_posix.startswith(prefix_slash):
            continue
        declared_figures.add(fig_posix[len(prefix_slash) :])
    paths = OverleafSyncPaths(
        main_repo=main_repo,
        overleaf_repo=overleaf_repo,
        path_in_project=path_in_project,
        sync_info_for_path=sync_info_for_path,
        last_sync_commit=last_sync_commit,
    )
    main_dir = os.path.join(str(main_repo.working_dir), path_in_project)
    overleaf_dir = str(overleaf_repo.working_dir)

    def _is_figure(rel_posix: str) -> bool:
        if rel_posix in declared_figures:
            return True
        return Path(rel_posix).suffix.lower() in FIGURE_EXTENSIONS

    def _describe(rel_posix: str, state: str) -> dict:
        return dict(
            path=rel_posix,
            project_path=prefix_slash + rel_posix,
            state=state,
            figure=_is_figure(rel_posix),
        )

    files_to_push = []
    for rel_posix in paths.files_to_copy_to_overleaf:
        main_fpath = os.path.join(main_dir, rel_posix)
        overleaf_fpath = os.path.join(overleaf_dir, rel_posix)
        if not os.path.isfile(overleaf_fpath):
            files_to_push.append(_describe(rel_posix, "new"))
            continue
        # Compare sizes before contents so unchanged large figures, which
        # are the common case, don't get read on every status check
        if os.path.getsize(main_fpath) != os.path.getsize(overleaf_fpath):
            files_to_push.append(_describe(rel_posix, "modified"))
            continue
        with open(main_fpath, "rb") as f1, open(overleaf_fpath, "rb") as f2:
            if f1.read() != f2.read():
                files_to_push.append(_describe(rel_posix, "modified"))
    files_to_delete = [
        _describe(rel_posix, "deleted")
        for rel_posix in paths.stale_files_in_overleaf
    ]
    commits_from_overleaf = get_commits_since_last_sync(
        overleaf_repo=overleaf_repo, last_sync_commit=last_sync_commit
    )
    return dict(
        path_in_project=path_in_project,
        overleaf_project_id=sync_info_for_path.get("project_id"),
        last_sync_commit=last_sync_commit,
        project_commit=main_repo.head.commit.hexsha,
        overleaf_commit=overleaf_repo.head.commit.hexsha,
        commits_from_overleaf=len(commits_from_overleaf),
        files_to_push=files_to_push,
        files_to_delete=files_to_delete,
        in_sync=(
            not files_to_push
            and not files_to_delete
            and not commits_from_overleaf
        ),
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
    under ``push_paths``, which are only pushed to Overleaf.

    Anything the pipeline produces is push-only, whichever way it's stored.
    Overleaf needs those files to compile the document, but an edit made to
    one there can't be pulled back: it would be overwritten by the next run,
    so it belongs in whatever the stage builds the file from. That includes
    the copies a ``map-paths`` stage puts in the document's folder (a shared
    ``references.bib``, say), which are pushed even though they're gitignored
    -- without them Overleaf can't compile.

    A map-paths copy is the one generated file whose edits have somewhere to
    go. When one is edited on Overleaf, the edit is written back to the file
    the stage copies it from, so the next run rebuilds the copy from it
    rather than discarding it. That doesn't apply when the source is itself
    generated by another stage; those edits are only reported.

    Other files that are ignored, untracked, or DVC pipeline outputs with no
    storage (``storage: null``, e.g., LaTeX build artifacts) are treated as
    ignored: never pushed to, pulled from, or deleted from Overleaf. A file is
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
    # Holds a mix of commits, paths, patches, and flags, so it's annotated
    # rather than inferred from whatever lands in it first.
    res: dict = {}
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
    # An edit made on Overleaf to a generated file is about to be overwritten
    # by this sync. A map-paths copy is the one case where the edit has
    # somewhere to go -- the file the stage copies from -- so it's sent there.
    # Anything else generated can only be reported.
    generated_edits = paths.pipeline_outputs_changed_on_overleaf
    res["pipeline_outputs_changed_on_overleaf"] = generated_edits
    map_paths_sources = paths.map_paths_sources
    edits_to_propagate = {
        dest: map_paths_sources[dest]
        for dest in generated_edits
        if dest in map_paths_sources
    }
    if push_only:
        edits_to_propagate = {}
    unrecoverable_edits = [
        dest for dest in generated_edits if dest not in edits_to_propagate
    ]
    if unrecoverable_edits and not push_only:
        print_info(
            "Warning: these files were changed on Overleaf but are generated "
            f"by the pipeline, so those changes will be overwritten: "
            f"{', '.join(unrecoverable_edits)}. Edit what the stage builds "
            "them from instead."
        )
    if push_only:
        # When push_only is True, skip pulling from Overleaf and applying
        # patches to local
        # Simply copy files to Overleaf
        print_info("Push-only sync; skipping pull from Overleaf")
        res["patch"] = None
    elif last_sync_commit and not paths_for_overleaf_patch:
        # Nothing on Overleaf is ours to pull. This needs its own branch
        # because an empty pathspec after `--` means "everything" to
        # format-patch, not "nothing", which would pull in exactly the files
        # we just decided to leave alone.
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
                os.makedirs(os.path.dirname(conflict_fpath), exist_ok=True)
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
    # Send Overleaf's edits to map-paths copies back to the files they're
    # copied from. This happens after any patch has been applied, since
    # 'git am' refuses to run against a dirty working tree.
    propagated: dict[str, str] = {}
    diverged: dict[str, str] = {}
    for dest_rel, src_rel in sorted(edits_to_propagate.items()):
        overleaf_version = os.path.join(overleaf_project_dir_abs, dest_rel)
        if not os.path.isfile(overleaf_version):
            # Deleted on Overleaf; deleting the source it's shared from is
            # not this sync's call to make
            continue
        source_fpath = os.path.join(main_repo.working_dir, src_rel)
        copy_fpath = os.path.join(path_in_project_abs, dest_rel)
        # The copy is what the source produced the last time the stage ran,
        # so a source that still matches it hasn't changed since. One that
        # doesn't has edits of its own, which an overwrite would destroy.
        if os.path.isfile(source_fpath) and os.path.isfile(copy_fpath):
            with open(source_fpath, "rb") as f1, open(copy_fpath, "rb") as f2:
                if f1.read() != f2.read():
                    diverged[dest_rel] = src_rel
                    continue
        os.makedirs(os.path.dirname(source_fpath) or ".", exist_ok=True)
        shutil.copy2(overleaf_version, source_fpath)
        # The copy in the document's folder is updated too, so this sync
        # doesn't push the pre-edit version straight back to Overleaf. The
        # next run rewrites it from the source anyway.
        os.makedirs(os.path.dirname(copy_fpath) or ".", exist_ok=True)
        shutil.copy2(overleaf_version, copy_fpath)
        propagated[dest_rel] = src_rel
    res["map_paths_propagated"] = propagated
    res["map_paths_diverged"] = diverged
    if propagated:
        for dest_rel, src_rel in sorted(propagated.items()):
            print_info(
                f"Applying Overleaf's change to {dest_rel} to {src_rel}, "
                "which it's copied from"
            )
        print_info("Run the pipeline to rebuild from the updated source(s)")
    for dest_rel, src_rel in sorted(diverged.items()):
        print_info(
            f"Warning: {dest_rel} was changed on Overleaf, but {src_rel}, "
            "which it's copied from, has changes of its own; leaving it "
            "alone. Run the pipeline and sync again, or merge the two by "
            "hand."
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
    auto_ignore_paths = {Path(p).as_posix() for p in calkit.AUTO_IGNORE_PATHS}
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
            or untracked_posix in auto_ignore_paths
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
    # Map-paths sources typically live outside the synced folder, so they
    # need staging by name. One stored with DVC rather than Git can't be
    # staged at all, so it's left for the user to save.
    for src_rel in sorted(set(propagated.values())):
        if main_repo.ignored(src_rel):
            print_info(
                f"Not committing {src_rel} since it's ignored by Git; "
                "save it with 'calkit save' if it's stored with DVC"
            )
            continue
        main_repo.git.add(src_rel)
        if src_rel not in paths_to_commit:
            paths_to_commit.append(src_rel)
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
