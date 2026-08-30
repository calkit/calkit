"""A document's components, judged from a repo tree.

``calkit.components`` decides what counts as out of date -- a stage that
needs a rerun, a project that has moved on since the document was built, an
answer that no longer matches its evidence, a file nobody accounts for.
This module only says how to reach a project's files when the project is a
Git tree at a ref rather than a checkout on someone's laptop, so the hub
and the CLI cannot end up giving two answers to the same question.
"""

from __future__ import annotations

import hashlib
import json
import logging
import posixpath
from typing import Any, Callable

import yaml

from app.git import RepoTree
from calkit.components import (  # type: ignore[import-untyped]
    Component,
    ProjectView,
    enrich,
)

logger = logging.getLogger("uvicorn.error")

# A results file bigger than this isn't read to compare one value against
# what the document was built with. Results files are small by nature; one
# this big is something else, and a value comparison isn't worth the
# download.
MAX_RESULTS_BYTES = 5_000_000
# The sidecar a build leaves beside a document
SIDECAR_SUFFIX = ".provenance.json"


def sidecar_path(document: str) -> str:
    """Where a document's provenance record lives, from any of its names."""
    for suffix in (SIDECAR_SUFFIX, ".pdf", ".tex"):
        if document.endswith(suffix):
            return document[: -len(suffix)] + SIDECAR_SUFFIX
    return document + SIDECAR_SUFFIX


class TreeProject(ProjectView):
    """A project as a Git tree at a ref, which is what the server has.

    Everything expensive is passed in already computed: the caller is
    reading the same tree for other reasons and shouldn't pay twice.
    """

    def __init__(
        self,
        ck_info: dict,
        tree: RepoTree,
        dvc_outs: dict[str, dict],
        stale_stage_names: set[str] | None,
        read_file: Callable[[str, int], bytes] | None = None,
    ) -> None:
        super().__init__(ck_info)
        self.tree = tree
        self.dvc_outs = dvc_outs
        self._stale_stage_names = stale_stage_names
        # How to get a file's bytes when the tree doesn't hold them, i.e.
        # when DVC does. Without one, only Git-tracked files can be read,
        # which is enough to place a component but not to compare a value.
        self.read_file = read_file
        self._results: dict[str, Any] = {}

    def exists(self, path: str) -> bool:
        # A DVC-tracked file isn't in the tree, but its pointer is, and it
        # is every bit as much the project's
        return (
            self.tree.is_file(path)
            or path in self.dvc_outs
            or self.tree.is_file(path + ".dvc")
        )

    def current_hash(self, path: str) -> str | None:
        out = self.dvc_outs.get(path)
        md5 = str(out.get("md5") or "") if out else ""
        if md5 and not md5.endswith(".dir"):
            return md5
        # A Git-stored output has no DVC entry, so its content is hashed
        # the way DVC would, which is what the sidecar recorded
        try:
            if self.tree.is_file(path):
                return hashlib.md5(self.tree.read_bytes(path)).hexdigest()
        except Exception as e:
            logger.warning(f"Could not hash {path}: {e}")
        return None

    def read_results(self, path: str) -> Any:
        if path in self._results:
            return self._results[path]
        data: bytes | None = None
        try:
            if self.tree.is_file(path):
                data = self.tree.read_bytes(path)
            elif self.read_file is not None:
                data = self.read_file(path, MAX_RESULTS_BYTES)
        except Exception as e:
            raise ValueError(f"Could not read {path}") from e
        if data is None:
            raise ValueError(f"Could not read {path}")
        if path.endswith(".json"):
            loaded = json.loads(data)
        elif path.endswith((".yaml", ".yml")):
            loaded = yaml.safe_load(data)
        else:
            raise ValueError(f"Not a results file: {path}")
        self._results[path] = loaded
        return loaded

    def stale_stages(self) -> set[str] | None:
        return self._stale_stage_names

    def stale_answers(self) -> set[str] | None:
        # Whether an answer still matches its evidence is judged from Git
        # history, which this doesn't have; saying nothing leaves a block
        # reading as unchecked rather than as fine
        return None


def read_sidecar(tree: RepoTree, document: str) -> dict | None:
    """A document's provenance record from the tree, if a build left one."""
    path = sidecar_path(document)
    try:
        if not tree.is_file(path):
            return None
        return json.loads(tree.read_bytes(path))
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
        return None


def stale_stage_base_names(
    stage_statuses: dict[str, Any],
) -> set[str]:
    """Stages needing a rerun, named as calkit.yaml names them.

    Pipeline status is keyed by the dvc.lock name, which carries an
    ``@expansion`` for an iterated stage; an output belongs to the stage as
    it is written in calkit.yaml. A stage that has never run needs running
    just as much as one whose inputs changed.
    """
    return {
        name.split("@")[0]
        for name, status in stage_statuses.items()
        if getattr(status, "status", None) in ("stale", "not-run")
    }


def components_for_document(
    document: str,
    tree: RepoTree,
    ck_info: dict,
    dvc_outs: dict[str, dict],
    stale_stage_names: set[str] | None,
    read_file: Callable[[str, int], bytes] | None = None,
) -> tuple[list[Component], bool]:
    """Everything a built document takes from the project, and its state.

    Returns the components and whether a build left a record to read at
    all. Without one there is nothing to say: the server has no LaTeX
    source resolution, and a document that has never been built with
    provenance on has no page for anything to appear on.
    """
    sidecar = read_sidecar(tree, document)
    if sidecar is None:
        return [], False
    view = TreeProject(
        ck_info=ck_info,
        tree=tree,
        dvc_outs=dvc_outs,
        stale_stage_names=stale_stage_names,
        read_file=read_file,
    )
    return enrich(sidecar.get("components") or [], view), True


def candidate_documents(ck_info: dict) -> list[str]:
    """Documents in the project that could have a provenance record.

    Every declared publication and every LaTeX stage's target, since a
    paper is usually both and either one alone is enough to find it.
    """
    documents: list[str] = []
    for pub in ck_info.get("publications") or []:
        if isinstance(pub, dict) and isinstance(pub.get("path"), str):
            documents.append(pub["path"])
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    for stage in stages.values():
        if (
            isinstance(stage, dict)
            and stage.get("kind") == "latex"
            and isinstance(stage.get("target_path"), str)
        ):
            documents.append(stage["target_path"])
    seen: set[str] = set()
    unique: list[str] = []
    for document in documents:
        path = sidecar_path(document)
        if path not in seen:
            seen.add(path)
            unique.append(document)
    return unique


def document_in(path: str, ck_info: dict) -> str:
    """The document a path names, whether it names the paper or its folder.

    A caller with the paper in hand names it; one with only the folder --
    the browser extension knows which folder syncs with an Overleaf
    project, not which file in it is the paper -- names that, and the
    project's own declarations say which document lives there. A folder
    holding more than one paper resolves to the first, which is the same
    choice made everywhere else a folder maps to several things.
    """
    if path.endswith((".tex", ".pdf", SIDECAR_SUFFIX)):
        return path
    prefix = path.strip("/")
    for document in candidate_documents(ck_info):
        if not prefix or document.startswith(prefix + "/"):
            return document
    return path


def usages_of(
    artifact_path: str,
    tree: RepoTree,
    ck_info: dict,
) -> list[dict]:
    """Where in the project's documents an artifact appears.

    The reverse of a document's components: given a figure or a results
    file, which papers show it and on which pages, so a change to a result
    shows what it touches. Read straight from the sidecars, with no
    staleness judged -- that is the document's page's job, not this one's.
    """
    artifact_path = posixpath.normpath(artifact_path)
    usages: list[dict] = []
    for document in candidate_documents(ck_info):
        sidecar = read_sidecar(tree, document)
        if sidecar is None:
            continue
        for component in sidecar.get("components") or []:
            if not isinstance(component, dict):
                continue
            if posixpath.normpath(str(component.get("path", ""))) != (
                artifact_path
            ):
                continue
            usages.append(
                {
                    "document": sidecar.get("document") or document,
                    "kind": component.get("kind"),
                    "key": component.get("key"),
                    "pages": component.get("pages") or [],
                }
            )
    usages.sort(key=lambda u: (u["document"], u["kind"], u["key"] or ""))
    return usages
