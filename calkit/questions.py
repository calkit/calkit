"""Checking a project's questions against their evidence.

An answer is a claim about the evidence as it was when the answer was last
edited. The pipeline keeps the evidence current, but nothing keeps the prose
current: re-run a stage, and a number an answer relies on can change without
anything noticing. Two things close that gap here, and neither copies a
value into ``calkit.yaml``.

Numbers are templated, not retyped. A ``value`` evidence entry names one
value in a results file, and the question's text can refer to it with
Python format syntax, ``"about {improvement:.1f}x"``; the text is rendered
from the file whenever it is shown, so a number in an answer is always the
pipeline's own.

Staleness comes from history, not from a record. Git already knows when a
question was last edited: the commit at which its entry in ``calkit.yaml``
last changed. If any of its evidence changed after that commit -- in Git
history for Git-tracked outputs, in ``dvc.lock`` for DVC-tracked ones --
the answer was written against evidence that no longer exists, and the
check reports it as stale until someone reads it again and edits the
question, which for an answer that still holds means setting ``reviewed``.

Both checks are deterministic and cheap. Judging whether the prose still
follows from changed evidence is neither, and is left to the reader or to
the ``check-questions`` agent skill, which uses this module's report to know
which questions to read.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import string
from typing import Any, Literal

from pydantic import BaseModel, Field

import calkit

EvidenceStatus = Literal["ok", "changed", "missing", "error", "skipped"]
QuestionStatus = Literal["ok", "stale", "error", "unanswered", "no-evidence"]
CALKIT_YAML = "calkit.yaml"


class EvidenceCheck(BaseModel):
    """The result of checking one evidence entry."""

    kind: str
    path: str
    key: str | None = None
    name: str | None = None
    status: EvidenceStatus
    message: str | None = None
    #: Current value, for value evidence
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
    #: Commit at which the question was last edited, if committed
    commit: str | None = None
    message: str | None = None
    evidence: list[EvidenceCheck] = Field(default_factory=list)


class QuestionsStatus(BaseModel):
    """The result of checking every question in a project."""

    questions: list[QuestionCheck] = Field(default_factory=list)

    @property
    def stale(self) -> list[QuestionCheck]:
        return [q for q in self.questions if q.status == "stale"]

    @property
    def errors(self) -> list[QuestionCheck]:
        return [q for q in self.questions if q.status == "error"]

    @property
    def answered(self) -> list[QuestionCheck]:
        return [q for q in self.questions if q.answered]

    @property
    def ok(self) -> bool:
        """True if no answered question is stale or broken."""
        return not self.stale and not self.errors


# -- values and templates ---------------------------------------------------


def read_evidence_file(path: str) -> Any:
    """Read a results file, by extension."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, encoding="utf-8") as f:
        if ext in (".yaml", ".yml"):
            return calkit.ryaml.load(f)
        if ext == ".json":
            return json.load(f)
    raise ValueError(
        f"Cannot read a value from {path}: only JSON and YAML results "
        "files are supported"
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
            try:
                node = node[int(part)]
            except IndexError:
                # An index past the end of a list is a key that isn't
                # there, and callers handle a missing key
                raise KeyError(key)
        else:
            raise KeyError(key)
    return node


class _Formatter(string.Formatter):
    """``str.format`` that treats the whole field name as a lookup key.

    The stock formatter reads ``{a.b}`` as attribute access and ``{a[0]}``
    as indexing, which would make a dotted evidence name unusable and would
    let a template reach into objects. Here a field name is only ever a
    name in the values mapping.
    """

    def get_field(self, field_name: str, args: Any, kwargs: Any) -> Any:
        if field_name not in kwargs:
            raise KeyError(field_name)
        return kwargs[field_name], field_name


_FORMATTER = _Formatter()
_PLACEHOLDER = re.compile(r"(?<!\{)\{([^{}:!]+)(?:[:!][^{}]*)?\}(?!\})")


def placeholders(text: str) -> list[str]:
    """Names referenced by ``{name...}`` placeholders in ``text``."""
    return [m.group(1) for m in _PLACEHOLDER.finditer(text or "")]


def render(text: str | None, values: dict[str, Any]) -> str | None:
    """Fill a question text's placeholders from its evidence values.

    Raises ``KeyError`` for a name with no evidence and ``ValueError`` for
    a format spec the value cannot satisfy, so a template that cannot be
    rendered is an error rather than a silently unfilled sentence.
    """
    if text is None or "{" not in text:
        return text
    return _FORMATTER.vformat(text, (), values)


def is_value_evidence(ev: dict) -> bool:
    """Whether an entry points at one value: ``value``, or the deprecated
    ``result`` with a ``key``."""
    kind = ev.get("kind", "result")
    return kind == "value" or (kind == "result" and bool(ev.get("key")))


def evidence_name(ev: dict) -> str | None:
    return ev.get("name") or ev.get("key")


TEMPLATED_FIELDS = ("hypothesis", "answer", "notes")


def render_question(
    question: str | dict, ck_info: dict | None = None, wdir: str | None = None
) -> str | dict:
    """A copy of a question with its templates filled from the evidence.

    A placeholder that cannot be filled is left as written rather than
    raising, since this is for display; ``check_questions`` is where a
    broken template is an error.
    """
    if isinstance(question, str):
        return question
    wdir = wdir or os.getcwd()
    values: dict[str, Any] = {}
    for ev in question.get("evidence") or []:
        if not is_value_evidence(ev):
            continue
        name = evidence_name(ev)
        try:
            data = read_evidence_file(os.path.join(wdir, ev["path"]))
            values[name or ""] = resolve_key(data, ev["key"])
        except Exception:
            continue
    out = dict(question)
    for field in TEMPLATED_FIELDS:
        try:
            out[field] = render(out.get(field), values)
        except (KeyError, ValueError, IndexError):
            pass
    if out.get("evidence"):
        rendered_evidence = []
        for ev in out["evidence"]:
            ev = dict(ev)
            try:
                ev["explanation"] = render(ev.get("explanation"), values)
            except (KeyError, ValueError, IndexError):
                pass
            rendered_evidence.append(ev)
        out["evidence"] = rendered_evidence
    return out


# -- history -------------------------------------------------------------


def _load_calkit_yaml_text(text: str) -> dict:
    loaded = calkit.ryaml.load(io.StringIO(text))
    return loaded if isinstance(loaded, dict) else {}


def _find_question(ck_info: dict, text: str) -> dict | None:
    for q in ck_info.get("questions", []) or []:
        if isinstance(q, dict) and q.get("question") == text:
            return q
    return None


def _plain(value: Any) -> Any:
    """Plain Python containers, so versions loaded by ruamel compare by
    content rather than by comment-bearing wrapper type."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def question_commit(question: dict, repo: Any, wdir: str) -> str | None:
    """The commit at which ``question`` last changed.

    Walks ``calkit.yaml``'s history back from HEAD while the question's
    entry is identical to the working tree's, and returns the oldest such
    commit. None means the working tree's version is not committed yet,
    or the file has no history.
    """
    rel = os.path.relpath(
        os.path.join(wdir, CALKIT_YAML), str(repo.working_dir)
    ).replace(os.sep, "/")
    try:
        shas = str(repo.git.log("--format=%H", "--", rel)).split()
    except Exception:
        return None
    text = question.get("question", "")
    current = _plain(question)
    found: str | None = None
    for sha in shas:
        try:
            old = _load_calkit_yaml_text(str(repo.git.show(f"{sha}:{rel}")))
        except Exception:
            break
        old_q = _find_question(old, text)
        if old_q is None or _plain(old_q) != current:
            break
        found = sha
    return found


def _lock_hash(lock_text: str, path: str) -> str | None:
    """The hash ``dvc.lock`` records for an output path, if any."""
    try:
        lock = _load_calkit_yaml_text(lock_text)
    except Exception:
        return None
    for stage in (lock.get("stages") or {}).values():
        for out in (stage or {}).get("outs") or []:
            if isinstance(out, dict) and out.get("path") == path:
                return str(out.get("md5") or out.get("hash") or "") or None
    return None


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return repr(value) if isinstance(value, str) else str(value)


def _values_equal(a: Any, b: Any) -> bool:
    """Equality that ignores the last bits of a float, so a change of BLAS
    or accumulation order does not count as the evidence changing."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b or abs(a - b) <= 1e-9 * max(abs(a), abs(b))
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(
            _values_equal(x, y) for x, y in zip(a, b)
        )
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(
            _values_equal(a[k], b[k]) for k in a
        )
    return bool(a == b)


def evidence_change(
    path: str,
    since: str,
    repo: Any,
    wdir: str,
    key: str | None = None,
    current: Any = None,
) -> str | None:
    """How ``path`` has changed since commit ``since``, or None if it has
    not.

    For a value in a Git-tracked results file the comparison is made on
    the value itself, read from the file as it was at ``since``: a results
    file gains keys and moves other numbers all the time, and none of that
    touches an answer that cites a different key. Other Git-tracked paths
    are asked directly. DVC-tracked ones are compared by the hash
    ``dvc.lock`` (or the path's ``.dvc`` file) recorded at that commit and
    now, which is the only record there is of a file Git does not hold.
    """
    root = str(repo.working_dir)
    rel = os.path.relpath(os.path.join(wdir, path), root).replace(os.sep, "/")
    short = since[:7]
    try:
        tracked = bool(str(repo.git.ls_files("--", rel)).strip())
    except Exception:
        tracked = False
    if tracked and key is not None:
        try:
            old_text = str(repo.git.show(f"{since}:{rel}"))
        except Exception:
            return f"{rel} did not exist at {short}"
        ext = os.path.splitext(rel)[1].lower()
        try:
            old_data = (
                json.loads(old_text)
                if ext == ".json"
                else calkit.ryaml.load(io.StringIO(old_text))
            )
            old = resolve_key(old_data, key)
        except KeyError:
            return f"{key} did not exist in {rel} at {short}"
        except Exception:
            return f"{rel} could not be read at {short}"
        if _values_equal(old, current):
            return None
        return f"{key} was {_fmt(old)} at {short}, now {_fmt(current)}"
    if tracked:
        commits = str(repo.git.rev_list(f"{since}..HEAD", "--", rel)).split()
        if commits:
            return f"changed in {len(commits)} commit(s) since {short}"
        if str(repo.git.diff("HEAD", "--name-only", "--", rel)).strip():
            return "modified in the working tree"
        return None
    pointer = rel + ".dvc"
    try:
        if str(repo.git.ls_files("--", pointer)).strip():
            commits = str(
                repo.git.rev_list(f"{since}..HEAD", "--", pointer)
            ).split()
            if commits:
                return f"{pointer} changed since {short}"
            return None
    except Exception:
        pass
    lock_rel = os.path.relpath(os.path.join(wdir, "dvc.lock"), root).replace(
        os.sep, "/"
    )
    try:
        old = _lock_hash(str(repo.git.show(f"{since}:{lock_rel}")), rel)
    except Exception:
        old = None
    try:
        with open(os.path.join(wdir, "dvc.lock"), encoding="utf-8") as f:
            new = _lock_hash(f.read(), rel)
    except OSError:
        new = None
    if old != new and (old or new):
        return f"hash in dvc.lock changed since {short}"
    return None


# -- checks --------------------------------------------------------------


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


def check_evidence(
    ev: dict, ck_info: dict, wdir: str, repo: Any, since: str | None
) -> EvidenceCheck:
    """Check one evidence entry against the working tree and history."""
    from calkit.pipeline import get_stage_for_output

    kind = ev.get("kind", "result")
    path = ev.get("path", "")
    key = ev.get("key")
    out = EvidenceCheck(
        kind=kind,
        path=path,
        key=key,
        name=evidence_name(ev) if is_value_evidence(ev) else None,
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
    if kind == "value" and not key:
        out.status = "error"
        out.message = "value evidence needs a key"
        return out
    if is_value_evidence(ev):
        try:
            out.current = resolve_key(
                read_evidence_file(os.path.join(wdir, path)), key or ""
            )
        except KeyError:
            out.status = "error"
            out.message = f"key {key!r} not found in {path}"
            return out
        except Exception as e:
            out.status = "error"
            out.message = f"cannot read {path}: {e.__class__.__name__}: {e}"
            return out
        if kind == "result":
            out.message = "a result with a key is a value; use kind: value"
    if since is not None and repo is not None:
        change = evidence_change(
            path,
            since,
            repo,
            wdir,
            key=key if is_value_evidence(ev) else None,
            current=out.current,
        )
        if change:
            out.status = "changed"
            out.message = change
    return out


def check_question(
    index: int,
    question: str | dict,
    ck_info: dict,
    wdir: str,
    repo: Any = None,
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
    since = question_commit(question, repo, wdir) if repo is not None else None
    checks = [
        check_evidence(ev, ck_info, wdir, repo, since) for ev in evidence
    ]
    messages: list[str] = []
    # Every placeholder in the prose must name a value and format with it
    values = {c.name: c.current for c in checks if c.name is not None}
    names = [c.name for c in checks if c.name is not None]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        messages.append(f"duplicate evidence name(s): {', '.join(dupes)}")
    texts = [question.get(f) for f in TEMPLATED_FIELDS] + [
        ev.get("explanation") for ev in evidence
    ]
    for t in texts:
        if not t or "{" not in t:
            continue
        try:
            render(t, values)
        except KeyError as e:
            messages.append(f"placeholder {{{e.args[0]}}} names no evidence")
        except (ValueError, IndexError) as e:
            messages.append(f"cannot render {t[:40]!r}...: {e}")
    statuses = {c.status for c in checks}
    status: QuestionStatus = "ok"
    if messages or statuses & {"error", "missing"}:
        status = "error"
    elif "changed" in statuses:
        status = "stale"
        messages.append(
            "evidence changed since the answer was last edited; re-read it "
            "and set 'reviewed' if it still holds"
        )
    if since is None and repo is not None:
        messages.append("not yet committed, so history cannot be checked")
    return QuestionCheck(
        index=index,
        question=text,
        answered=True,
        status=status,
        commit=since,
        message="; ".join(messages) or None,
        evidence=checks,
    )


def check_questions(
    ck_info: dict | None = None, wdir: str | None = None
) -> QuestionsStatus:
    """Check every question in a project against its evidence."""
    wdir = wdir or os.getcwd()
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    try:
        repo = calkit.git.get_repo(wdir)
    except Exception:
        repo = None
    questions = ck_info.get("questions", []) or []
    return QuestionsStatus(
        questions=[
            check_question(n, q, ck_info, wdir, repo)
            for n, q in enumerate(questions, start=1)
        ]
    )


def format_status(status: QuestionsStatus, verbose: bool = False) -> str:
    """A human-readable report, one block per question needing attention.

    With ``verbose``, every answered question is listed with its evidence.
    """
    lines: list[str] = []
    answered = status.answered
    if not status.questions:
        return "No questions defined."
    for q in status.questions:
        needs_attention = q.status in ("stale", "error")
        if not verbose and not needs_attention:
            continue
        lines.append(f"{q.index}. [{q.status}] {q.question}")
        if q.message:
            lines.append(f"     {q.message}")
        for ev in q.evidence:
            if not verbose and ev.status in ("ok", "skipped"):
                continue
            where = f"{ev.path}" + (f":{ev.key}" if ev.key else "")
            detail = f" -- {ev.message}" if ev.message else ""
            lines.append(f"     {ev.kind} {where} [{ev.status}]{detail}")
    n_ok = sum(1 for q in answered if q.status == "ok")
    summary = (
        f"{len(answered)} answered question(s): {n_ok} consistent with "
        f"their evidence, {len(status.stale)} stale, {len(status.errors)} "
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
