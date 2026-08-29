"""Checking a project's questions against their evidence.

An answer is a claim about what the pipeline produced at the time it was
written. The pipeline keeps the evidence current, but nothing keeps the prose
current: re-run a stage, and a number an answer quotes can change without
anything noticing. So a ``result`` evidence entry can record the ``value``
its answer was written against, and this module compares that record with
what the evidence file holds now. A difference means the answer needs a
human to read it again. It may still be right, but nothing can say so
without reading it, so the check reports the question as stale until the
value is re-recorded with ``calkit update questions``.

The comparison is deterministic and cheap. Judging whether the prose still
follows from changed numbers is neither, and is left to the reader or to the
``check-questions`` agent skill, which uses this module's report to know
which questions to read.
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
from typing import Any, Literal

from pydantic import BaseModel

import calkit

#: Relative tolerance used to compare a recorded value with the current one
#: when the evidence entry does not set its own. Loose enough that a change
#: of BLAS or accumulation order does not flag an answer, tight enough that
#: any change a reader could see does.
DEFAULT_TOLERANCE = 1e-6

EvidenceStatus = Literal[
    "ok", "stale", "unrecorded", "missing", "error", "skipped"
]
QuestionStatus = Literal[
    "ok", "stale", "unrecorded", "error", "unanswered", "no-evidence"
]


class EvidenceCheck(BaseModel):
    """The result of checking one evidence entry."""

    kind: str
    path: str
    key: str | None = None
    status: EvidenceStatus
    message: str | None = None
    recorded: Any = None
    current: Any = None
    #: The pipeline stage that produces the path, if any
    stage: str | None = None


class QuestionCheck(BaseModel):
    """The result of checking one question."""

    #: 1-based, matching ``calkit list questions``
    index: int
    question: str
    answered: bool
    status: QuestionStatus
    evidence: list[EvidenceCheck] = []


class QuestionsStatus(BaseModel):
    """The result of checking every question in a project."""

    questions: list[QuestionCheck] = []

    @property
    def stale(self) -> list[QuestionCheck]:
        return [q for q in self.questions if q.status == "stale"]

    @property
    def errors(self) -> list[QuestionCheck]:
        return [q for q in self.questions if q.status == "error"]

    @property
    def unrecorded(self) -> list[QuestionCheck]:
        return [q for q in self.questions if q.status == "unrecorded"]

    @property
    def answered(self) -> list[QuestionCheck]:
        return [q for q in self.questions if q.answered]

    @property
    def ok(self) -> bool:
        """True if no answered question is stale or broken."""
        return not self.stale and not self.errors


def read_evidence_file(path: str) -> Any:
    """Read a results file, by extension."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, encoding="utf-8") as f:
        if ext in (".yaml", ".yml"):
            return calkit.ryaml.load(f)
        if ext == ".json":
            return json.load(f)
    raise ValueError(
        f"Cannot read a keyed value from {path}: only JSON and YAML "
        "results files are supported"
    )


def resolve_key(data: Any, key: str) -> Any:
    """Look up ``key`` in a loaded results file.

    A key that exists literally at the top level wins, so a key containing
    dots keeps working. Otherwise the key is split on dots and walked, with
    integer parts indexing into lists, so ``results.case-a.score`` reaches
    into nested output.
    """
    if isinstance(data, dict) and key in data:
        return data[key]
    node = data
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and re.fullmatch(r"-?\d+", part):
            node = node[int(part)]
        else:
            raise KeyError(key)
    return node


def values_match(
    recorded: Any, current: Any, tolerance: float | None = None
) -> bool:
    """Compare a recorded evidence value with the current one.

    Numbers are compared with a relative tolerance (``DEFAULT_TOLERANCE``
    unless the entry sets its own); everything else must be equal, with
    lists and dicts compared element-wise under the same rule. Booleans are
    exact, since ``True`` is also ``1``.
    """
    tol = DEFAULT_TOLERANCE if tolerance is None else tolerance
    if isinstance(recorded, bool) or isinstance(current, bool):
        return recorded is current
    if isinstance(recorded, (int, float)) and isinstance(
        current, (int, float)
    ):
        a, b = float(recorded), float(current)
        if math.isnan(a) and math.isnan(b):
            return True
        if math.isinf(a) or math.isinf(b):
            return a == b
        return abs(a - b) <= tol * max(abs(a), abs(b), 0.0) or a == b
    if isinstance(recorded, list) and isinstance(current, list):
        return len(recorded) == len(current) and all(
            values_match(r, c, tolerance) for r, c in zip(recorded, current)
        )
    if isinstance(recorded, dict) and isinstance(current, dict):
        return recorded.keys() == current.keys() and all(
            values_match(recorded[k], current[k], tolerance) for k in recorded
        )
    return bool(recorded == current)


def _find_latex_sources(pdf_path: str, ck_info: dict, wdir: str) -> list[str]:
    """The ``.tex`` files that could carry a label for a built PDF.

    Found through the LaTeX stage that produces the PDF: its target and every
    ``.tex`` beside or below it, since documents are commonly split with
    ``\\input``.
    """
    from calkit.pipeline import get_stage_for_output

    stage_name = get_stage_for_output(pdf_path, ck_info)
    stages = ck_info.get("pipeline", {}).get("stages", {})
    stage = stages.get(stage_name) if stage_name else None
    if not isinstance(stage, dict) or stage.get("kind") != "latex":
        return []
    target = stage.get("target_path")
    if not target:
        return []
    root = os.path.join(wdir, os.path.dirname(target))
    return sorted(glob.glob(os.path.join(root, "**", "*.tex"), recursive=True))


def _check_publication_label(
    ev: dict, ck_info: dict, wdir: str
) -> tuple[EvidenceStatus, str | None]:
    label = ev.get("label")
    if not label:
        return "ok", None
    sources = _find_latex_sources(ev["path"], ck_info, wdir)
    if not sources:
        return "skipped", (
            f"label {label!r} not checked: no LaTeX stage produces "
            f"{ev['path']}"
        )
    pattern = re.compile(r"\\label\{" + re.escape(label) + r"\}")
    for src in sources:
        with open(src, encoding="utf-8", errors="replace") as f:
            if pattern.search(f.read()):
                return "ok", None
    return "error", (
        f"label {label!r} not found in {len(sources)} LaTeX source file(s) "
        f"under {os.path.dirname(sources[0])}"
    )


def check_evidence(ev: dict, ck_info: dict, wdir: str) -> EvidenceCheck:
    """Check one evidence entry against the working tree."""
    from calkit.pipeline import get_stage_for_output

    kind = ev.get("kind", "result")
    path = ev.get("path", "")
    key = ev.get("key")
    out = EvidenceCheck(
        kind=kind,
        path=path,
        key=key,
        status="ok",
        stage=get_stage_for_output(path, ck_info) if path else None,
    )
    if not path:
        out.status = "error"
        out.message = "evidence has no path"
        return out
    if not os.path.exists(os.path.join(wdir, path)):
        out.status = "missing"
        out.message = "path does not exist; run the pipeline or pull"
        return out
    if kind == "publication":
        out.status, out.message = _check_publication_label(ev, ck_info, wdir)
        return out
    if kind != "result" or key is None:
        # A figure, a table, or a whole results file: nothing to compare
        # beyond existence
        return out
    try:
        data = read_evidence_file(os.path.join(wdir, path))
        current = resolve_key(data, key)
    except KeyError:
        out.status = "error"
        out.message = f"key {key!r} not found in {path}"
        return out
    except Exception as e:
        out.status = "error"
        out.message = f"cannot read {path}: {e.__class__.__name__}: {e}"
        return out
    out.current = current
    if "value" not in ev:
        out.status = "unrecorded"
        out.message = (
            "no recorded value to compare against; run "
            "'calkit update questions' to record the current one"
        )
        return out
    out.recorded = ev["value"]
    if values_match(out.recorded, current, ev.get("tolerance")):
        return out
    out.status = "stale"
    out.message = (
        f"{key} changed from {_fmt(out.recorded)} to {_fmt(current)} "
        "since the answer was written"
    )
    return out


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return repr(value) if isinstance(value, str) else str(value)


def check_question(
    index: int, question: str | dict, ck_info: dict, wdir: str
) -> QuestionCheck:
    """Check one question, as it appears in ``calkit.yaml``."""
    if isinstance(question, str):
        return QuestionCheck(
            index=index, question=question, answered=False, status="unanswered"
        )
    text = question.get("question", "")
    answered = bool(question.get("answer"))
    evidence = question.get("evidence") or []
    if not answered:
        return QuestionCheck(
            index=index, question=text, answered=False, status="unanswered"
        )
    if not evidence:
        return QuestionCheck(
            index=index, question=text, answered=True, status="no-evidence"
        )
    checks = [check_evidence(ev, ck_info, wdir) for ev in evidence]
    statuses = {c.status for c in checks}
    status: QuestionStatus = "ok"
    if statuses & {"error", "missing"}:
        status = "error"
    elif "stale" in statuses:
        status = "stale"
    elif "unrecorded" in statuses:
        status = "unrecorded"
    return QuestionCheck(
        index=index,
        question=text,
        answered=True,
        status=status,
        evidence=checks,
    )


def check_questions(
    ck_info: dict | None = None, wdir: str | None = None
) -> QuestionsStatus:
    """Check every question in a project against its evidence."""
    wdir = wdir or os.getcwd()
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    questions = ck_info.get("questions", []) or []
    return QuestionsStatus(
        questions=[
            check_question(n, q, ck_info, wdir)
            for n, q in enumerate(questions, start=1)
        ]
    )


def record_evidence_values(
    ck_info: dict,
    wdir: str | None = None,
    indices: list[int] | None = None,
    force: bool = False,
) -> list[tuple[int, str, Any, Any]]:
    """Record the current value of each keyed result evidence entry.

    Modifies ``ck_info`` in place and returns what changed as
    ``(question index, key, old value, new value)`` tuples. Only questions
    whose answers have just been written or reviewed should be recorded,
    which is what ``indices`` is for; recording everything with ``force``
    declares every answer current, so it is a deliberate act rather than
    the default.

    A value is recorded when the entry has none, or when it has one that no
    longer matches; matching values are left alone so a re-record does not
    churn the last significant figures.
    """
    wdir = wdir or os.getcwd()
    changed: list[tuple[int, str, Any, Any]] = []
    questions = ck_info.get("questions", []) or []
    for n, q in enumerate(questions, start=1):
        if indices is not None and n not in indices:
            continue
        if not isinstance(q, dict) or not q.get("answer"):
            continue
        for ev in q.get("evidence") or []:
            if ev.get("kind", "result") != "result" or not ev.get("key"):
                continue
            data = read_evidence_file(os.path.join(wdir, ev["path"]))
            current = resolve_key(data, ev["key"])
            had = "value" in ev
            if (
                had
                and not force
                and values_match(ev["value"], current, ev.get("tolerance"))
            ):
                continue
            old = ev.get("value")
            ev["value"] = _plain(current)
            changed.append((n, ev["key"], old, ev["value"]))
    return changed


def _plain(value: Any) -> Any:
    """Convert numpy-ish scalars and containers to plain YAML-able values."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "item") and callable(value.item):
        return value.item()
    return value


def format_status(status: QuestionsStatus, verbose: bool = False) -> str:
    """A human-readable report, one line per question that needs attention.

    With ``verbose``, every answered question is listed with its evidence.
    """
    lines: list[str] = []
    answered = status.answered
    if not status.questions:
        return "No questions defined."
    for q in status.questions:
        needs_attention = q.status in ("stale", "error", "unrecorded")
        if not verbose and not needs_attention:
            continue
        lines.append(f"{q.index}. [{q.status}] {q.question}")
        for ev in q.evidence:
            if not verbose and ev.status in ("ok", "skipped"):
                continue
            where = f"{ev.path}" + (f":{ev.key}" if ev.key else "")
            detail = f" -- {ev.message}" if ev.message else ""
            lines.append(f"     {ev.kind} {where} [{ev.status}]{detail}")
    n_ok = sum(1 for q in answered if q.status == "ok")
    summary = (
        f"{len(answered)} answered question(s): {n_ok} consistent with "
        f"recorded evidence, {len(status.stale)} stale, "
        f"{len(status.unrecorded)} unrecorded, {len(status.errors)} "
        "with errors"
    )
    no_evidence = sum(1 for q in answered if q.status == "no-evidence")
    if no_evidence:
        summary += f"; {no_evidence} answered without evidence"
    unanswered = len(status.questions) - len(answered)
    if unanswered:
        summary += f"; {unanswered} unanswered"
    lines.append(summary)
    return "\n".join(lines)
