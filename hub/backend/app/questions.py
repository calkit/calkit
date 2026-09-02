"""A project's questions, judged from a repo at a ref.

``calkit.questions`` decides whether an answer still follows from its
evidence: whether each cited path is still there, whether the value behind
a placeholder has moved since the answer was last edited, whether anything
records where the evidence came from. This module only says how to reach a
project's files and history when the project is a Git tree at a ref rather
than a checkout on someone's laptop, so the hub and the CLI cannot end up
giving two answers to the same question.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import yaml

from app.git import RepoTree
from calkit.questions import (  # type: ignore[import-untyped]
    QuestionsStatus,
    QuestionsView,
    check_questions,
)

logger = logging.getLogger("uvicorn.error")

# A results file bigger than this is not read to compare one value against
# what an answer cited. Results files are small by nature.
MAX_RESULTS_BYTES = 5_000_000


class RepoTreeQuestions(QuestionsView):
    """The project as a Git tree, with history read from the same repo."""

    def __init__(self, tree: RepoTree, ref: str, wdir: str) -> None:
        self.tree = tree
        self.ref = ref
        # The clone's own root: the hub serves whole repos, so a project's
        # paths are already repo-relative
        self.wdir = wdir
        self._results: dict[str, Any] = {}

    def exists(self, path: str) -> bool:
        # A DVC-tracked file is not in the tree, but its pointer is, and
        # the project has it every bit as much
        return self.tree.is_file(path) or self.tree.is_file(path + ".dvc")

    def read_results(self, path: str) -> Any:
        if path in self._results:
            return self._results[path]
        if not self.tree.is_file(path):
            raise ValueError(f"Could not read {path}")
        data = self.tree.read_bytes(path)
        if len(data) > MAX_RESULTS_BYTES:
            raise ValueError(f"{path} is too big to read")
        if path.endswith(".json"):
            loaded = json.loads(data)
        elif path.endswith((".yaml", ".yml")):
            loaded = yaml.safe_load(data)
        else:
            raise ValueError(f"Not a results file: {path}")
        self._results[path] = loaded
        return loaded

    def in_dvc_lock(self, path: str) -> bool:
        from calkit.questions import lock_hash

        try:
            if not self.tree.is_file("dvc.lock"):
                return False
            text = self.tree.read_bytes("dvc.lock").decode("utf-8", "replace")
        except Exception:
            return False
        return lock_hash(text, path) is not None

    # latex_sources is left as the base class has it: None, meaning labels
    # are not checked here rather than checked and not found. Finding them
    # means globbing every .tex beside a document, which is a tree walk per
    # publication evidence entry, and a label going missing is something
    # the person editing the document sees first anyway.


def questions_status(
    ck_info: dict,
    tree: RepoTree,
    repo: Any,
    ref: str,
) -> QuestionsStatus | None:
    """Check a project's questions as of one ref, or None if it cannot be.

    None rather than an empty status: a project whose questions could not
    be read has not been found to be fine, and saying nothing is the only
    honest thing to show for it.
    """
    try:
        return check_questions(
            ck_info=ck_info,
            view=RepoTreeQuestions(
                tree=tree, ref=ref, wdir=str(repo.working_dir)
            ),
            repo=repo,
        )
    except Exception as e:
        logger.warning(f"Could not check questions at {ref}: {e}")
        return None
