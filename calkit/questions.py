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
question, which for an answer that still holds means editing it after
reading it again.

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
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

import calkit

EvidenceStatus = Literal[
    "ok", "changed", "missing", "error", "skipped", "unattributed"
]
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

    @property
    def unattributed(self) -> list[EvidenceCheck]:
        """Evidence entries nothing in the project accounts for."""
        return [
            ev
            for q in self.questions
            for ev in q.evidence
            if ev.status == "unattributed"
        ]

    @property
    def deprecated(self) -> list[EvidenceCheck]:
        """Evidence entries still written as a 'result' with a key."""
        return [
            ev
            for q in self.questions
            for ev in q.evidence
            if ev.kind == "result" and ev.key
        ]


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
    question: str | dict,
    ck_info: dict | None = None,
    wdir: str | None = None,
    read_evidence: Callable[[str], Any] | None = None,
) -> str | dict:
    """A copy of a question with its templates filled from the evidence.

    A placeholder that cannot be filled is left as written rather than
    raising, since this is for display; ``check_questions`` is where a
    broken template is an error.

    ``read_evidence`` loads a results file given its project-relative
    path, for a caller whose project is not a directory on a disk --- the
    hub reads a Git tree at a ref. Without one the path is read from
    ``wdir``, which is what the CLI wants. Injecting the reading rather
    than reimplementing the rendering is what keeps the hub and the CLI
    from filling the same sentence two different ways.
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
            if read_evidence is not None:
                data = read_evidence(ev["path"])
            else:
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
    """Parse a historical ``calkit.yaml``.

    PyYAML rather than the round-trip parser: none of this is written back,
    and history is read a commit at a time, where the round-trip parser's
    comment and formatting bookkeeping is most of the cost.
    """
    import yaml

    try:
        loaded = yaml.safe_load(io.StringIO(text))
    except yaml.YAMLError:
        # A revision whose calkit.yaml uses something PyYAML refuses is
        # still worth reading; the round-trip parser is more forgiving
        loaded = calkit.ryaml.load(io.StringIO(text))
    return loaded if isinstance(loaded, dict) else {}


class CalkitYamlHistory:
    """``calkit.yaml`` as it was at each commit, read once and shared.

    Finding the commit a question was last edited at walks the file's
    history until the question differs, and every question walks the same
    history. Without this each of them re-runs ``git show`` and re-parses
    the same revisions: with Q questions and C commits that is Q x C
    subprocesses to answer C commits' worth of history, which is what made
    checking a handful of questions take double-digit seconds.
    """

    def __init__(self, repo: Any, wdir: str, ref: str | None = None) -> None:
        self.repo = repo
        self.rel = os.path.relpath(
            os.path.join(wdir, CALKIT_YAML), str(repo.working_dir)
        ).replace(os.sep, "/")
        # Where the walk starts. None means the checkout's own HEAD, which
        # is what the CLI wants; a server browsing a ref has to say so,
        # since its clone sits on whatever branch it last happened to.
        self.ref = ref
        self._shas: list[str] | None = None
        self._parsed: dict[str, dict | None] = {}

    @property
    def shas(self) -> list[str]:
        """Commits that touched the file, newest first."""
        if self._shas is None:
            args = ["--format=%H"] + ([self.ref] if self.ref else [])
            try:
                self._shas = str(
                    self.repo.git.log(*args, "--", self.rel)
                ).split()
            except Exception:
                self._shas = []
        return self._shas

    def at(self, sha: str) -> dict | None:
        """The file as of one commit, or None if it can't be read.

        Read straight out of the object database rather than by shelling
        out to ``git show`` per commit, which is twenty times the cost for
        the same bytes.
        """
        if sha not in self._parsed:
            try:
                blob = self.repo.rev_parse(f"{sha}:{self.rel}")
                text = blob.data_stream.read().decode("utf-8", "replace")
                self._parsed[sha] = _load_calkit_yaml_text(text)
            except Exception:
                self._parsed[sha] = None
        return self._parsed[sha]


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


def question_commit(
    question: dict,
    repo: Any,
    wdir: str,
    history: CalkitYamlHistory | None = None,
) -> str | None:
    """The commit at which ``question`` last changed.

    Walks ``calkit.yaml``'s history back from HEAD while the question's
    entry is identical to the working tree's, and returns the oldest such
    commit. None means the working tree's version is not committed yet,
    or the file has no history.

    ``history`` is shared across questions when there is more than one, so
    each revision is read and parsed once rather than once per question.
    """
    if history is None:
        history = CalkitYamlHistory(repo, wdir)
    text = question.get("question", "")
    current = _plain(question)
    found: str | None = None
    for sha in history.shas:
        old = history.at(sha)
        if old is None:
            break
        old_q = _find_question(old, text)
        if old_q is None or _plain(old_q) != current:
            break
        found = sha
    return found


def lock_hash(lock_text: str, path: str) -> str | None:
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
    ref: str | None = None,
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

    ``ref`` is what "now" means. None is the checkout: its HEAD, plus
    anything modified in the working tree, which is what someone running
    this on their own project is asking about. A server browsing a ref
    passes it, and the working tree --- which belongs to whatever branch
    its clone happens to sit on --- is left out of the comparison.
    """
    root = str(repo.working_dir)
    rel = os.path.relpath(os.path.join(wdir, path), root).replace(os.sep, "/")
    short = since[:7]
    head = ref or "HEAD"
    try:
        tracked = bool(
            str(
                repo.git.ls_tree(head, "--", rel)
                if ref
                else repo.git.ls_files("--", rel)
            ).strip()
        )
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
        commits = str(repo.git.rev_list(f"{since}..{head}", "--", rel)).split()
        if commits:
            return f"changed in {len(commits)} commit(s) since {short}"
        if (
            ref is None
            and str(repo.git.diff("HEAD", "--name-only", "--", rel)).strip()
        ):
            return "modified in the working tree"
        return None
    pointer = rel + ".dvc"
    try:
        if str(
            repo.git.ls_tree(head, "--", pointer)
            if ref
            else repo.git.ls_files("--", pointer)
        ).strip():
            commits = str(
                repo.git.rev_list(f"{since}..{head}", "--", pointer)
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
        old = lock_hash(str(repo.git.show(f"{since}:{lock_rel}")), rel)
    except Exception:
        old = None
    try:
        if ref:
            new = lock_hash(str(repo.git.show(f"{ref}:{lock_rel}")), rel)
        else:
            with open(os.path.join(wdir, "dvc.lock"), encoding="utf-8") as f:
                new = lock_hash(f.read(), rel)
    except Exception:
        new = None
    if old != new and (old or new):
        return f"hash in dvc.lock changed since {short}"
    return None


# -- checks --------------------------------------------------------------


class QuestionsView:
    """What checking a question against its evidence needs of a project.

    Everything written down in ``calkit.yaml`` is answered from it, so the
    judgment about whether an answer still follows from its evidence stays
    in one place. Reaching the project's files is left to a subclass,
    because where they are differs: the CLI has a working directory, and a
    server has a Git tree at some ref.

    This is the same split :class:`calkit.components.ProjectView` makes,
    for the same reason --- two implementations of the judgment would
    eventually give two answers.
    """

    #: What "now" means to Git. None is the checkout: its HEAD, plus
    #: anything modified in the working tree.
    ref: str | None = None
    #: Where the project sits inside the repo, for turning its paths into
    #: repo-relative ones. A server reading a tree is already at the root.
    wdir: str = "."

    def exists(self, path: str) -> bool:
        """Whether the project still has this file."""
        raise NotImplementedError

    def read_results(self, path: str) -> Any:
        """A results file, loaded. Raises if it cannot be read."""
        raise NotImplementedError

    def in_dvc_lock(self, path: str) -> bool:
        """Whether ``dvc.lock`` records this path as an output.

        A stage Calkit did not compile still leaves its outputs here, so a
        path with no Calkit stage can still be accounted for.
        """
        return False

    def latex_sources(self, pdf_path: str, ck_info: dict) -> list[str] | None:
        """Sources that could carry a label for a built PDF.

        None means labels cannot be checked here at all, which reads as
        skipped rather than as a label that is missing --- the difference
        between not looking and not finding.
        """
        return None

    def read_text(self, path: str) -> str:
        """A source file's text. Raises if it cannot be read."""
        raise NotImplementedError


class LocalQuestions(QuestionsView):
    """A project as a working directory, which is what the CLI has."""

    def __init__(self, wdir: str) -> None:
        self.wdir = wdir

    def exists(self, path: str) -> bool:
        return os.path.exists(os.path.join(self.wdir, path))

    def read_results(self, path: str) -> Any:
        return read_evidence_file(os.path.join(self.wdir, path))

    def in_dvc_lock(self, path: str) -> bool:
        try:
            with open(
                os.path.join(self.wdir, "dvc.lock"), encoding="utf-8"
            ) as f:
                return lock_hash(f.read(), path) is not None
        except OSError:
            return False

    def latex_sources(self, pdf_path: str, ck_info: dict) -> list[str] | None:
        return _find_latex_sources(pdf_path, ck_info, self.wdir)

    def read_text(self, path: str) -> str:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()


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
    ev: dict, ck_info: dict, view: QuestionsView
) -> tuple[EvidenceStatus, str | None]:
    label = ev.get("label")
    if not label:
        return "ok", None
    sources = view.latex_sources(ev["path"], ck_info)
    if sources is None:
        return "skipped", f"label {label!r} not checked here"
    if not sources:
        return "skipped", (
            f"label {label!r} not checked: no LaTeX stage produces "
            f"{ev['path']}"
        )
    pattern = re.compile(r"\\label\{" + re.escape(label) + r"\}")
    for src in sources:
        try:
            text = view.read_text(src)
        except Exception:
            continue
        if pattern.search(text):
            return "ok", None
    return "error", (
        f"label {label!r} not found in {len(sources)} LaTeX source file(s) "
        f"under {os.path.dirname(sources[0])}"
    )


def _is_attributed(
    path: str, stage: str | None, ck_info: dict, view: QuestionsView
) -> bool:
    """Whether the project says where an evidence path came from.

    A pipeline stage is the strong form, in ``calkit.yaml`` or, for a
    stage Calkit did not compile, in ``dvc.lock``. Failing that, the path
    may be declared as an artifact that records an import or a person,
    which is what :func:`calkit.provenance.has_provenance` reads---an
    imported dataset or a hand-drawn schematic is accounted for even
    though there is nothing upstream to point at.
    """
    from calkit.provenance import has_provenance

    if stage is not None:
        return True
    if view.in_dvc_lock(path):
        return True
    for artifacts in ck_info.values():
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if (
                isinstance(artifact, dict)
                and artifact.get("path") == path
                and has_provenance(artifact)
            ):
                return True
    return False


def check_evidence(
    ev: dict,
    ck_info: dict,
    view: QuestionsView,
    repo: Any,
    since: str | None,
) -> EvidenceCheck:
    """Check one evidence entry against the project and its history."""
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
    if not view.exists(path):
        out.status = "missing"
        out.message = "path does not exist; run the pipeline or pull"
        return out
    if kind == "publication":
        out.status, out.message = _check_publication_label(ev, ck_info, view)
        return out
    if kind == "value" and not key:
        out.status = "error"
        out.message = "value evidence needs a key"
        return out
    if is_value_evidence(ev):
        try:
            out.current = resolve_key(view.read_results(path), key or "")
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
            view.wdir,
            key=key if is_value_evidence(ev) else None,
            current=out.current,
            ref=view.ref,
        )
        if change:
            out.status = "changed"
            # Not overwritten: a deprecated entry that also changed is
            # still worth migrating, and the hint is the only place it is
            # said
            out.message = "; ".join(filter(None, [out.message, change]))
    if out.status == "ok" and not _is_attributed(
        path, out.stage, ck_info, view
    ):
        out.status = "unattributed"
        out.message = (
            "nothing says where this came from; produce it with a pipeline "
            "stage, or record it under figures, datasets, or publications "
            "with 'imported_from' or 'created_by'"
        )
    return out


def check_question(
    index: int,
    question: str | dict,
    ck_info: dict,
    view: QuestionsView,
    repo: Any = None,
    history: CalkitYamlHistory | None = None,
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
    since = (
        question_commit(question, repo, view.wdir, history)
        if repo is not None
        else None
    )
    checks = [
        check_evidence(ev, ck_info, view, repo, since) for ev in evidence
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
            messages.append(
                f"placeholder {{{e.args[0]}}} names no evidence; write "
                "'{{' and '}}' for braces meant to stay in the text"
            )
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
            "and edit the question if it still holds"
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
    ck_info: dict | None = None,
    wdir: str | None = None,
    view: QuestionsView | None = None,
    repo: Any = None,
) -> QuestionsStatus:
    """Check every question in a project against its evidence.

    ``view`` says how to reach the project's files, and ``repo`` how to
    reach its history. Without either, both are taken from ``wdir``, which
    is the checkout the CLI runs in. A server passes a view over a Git
    tree at the ref it is serving, and the same judgment answers for it.
    """
    wdir = wdir or os.getcwd()
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    if view is None:
        view = LocalQuestions(wdir)
    if repo is None:
        try:
            repo = calkit.git.get_repo(wdir)
        except Exception:
            repo = None
    questions = ck_info.get("questions", []) or []
    # One reading of calkit.yaml's history for all of them
    history = (
        CalkitYamlHistory(repo, view.wdir, ref=view.ref)
        if repo is not None
        else None
    )
    return QuestionsStatus(
        questions=[
            check_question(n, q, ck_info, view, repo, history)
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
        # An unattributed entry is advisory rather than a failure, but it
        # is only ever said here, so it earns the question a block
        needs_attention = q.status in ("stale", "error") or any(
            ev.status == "unattributed" for ev in q.evidence
        )
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
    if lines:
        lines.append("")
    n_ok = sum(1 for q in answered if q.status == "ok")
    lines.append(
        f"Questions answered: {len(answered)}/{len(status.questions)}"
    )
    if answered:
        lines.append(
            f"Answers consistent with their evidence: {n_ok}/{len(answered)} "
            f"{calkit.check_or_x(n_ok == len(answered))}"
        )
        lines.append(
            f"Answers whose evidence changed since: {len(status.stale)} "
            f"{calkit.check_or_x(not status.stale)}"
        )
        lines.append(
            f"Answers with broken references: {len(status.errors)} "
            f"{calkit.check_or_x(not status.errors)}"
        )
    # No check mark either way on the rest: worth a look, not a verdict
    no_evidence = sum(1 for q in answered if q.status == "no-evidence")
    if no_evidence:
        lines.append(
            f"Answers given without evidence: {no_evidence} (worth a look)"
        )
    if status.unattributed:
        lines.append(
            "Evidence with nothing recorded behind it: "
            f"{len(status.unattributed)} (worth a look)"
        )
    if status.deprecated:
        lines.append(
            f"Evidence written as a 'result' with a key: "
            f"{len(status.deprecated)} (use 'kind: value')"
        )
    return "\n".join(lines)
