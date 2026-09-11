"""Checking a project's questions against their evidence.

An answer is a claim about evidence, and the check asks whether that
evidence is there and current. Nothing here judges the prose.

Numbers are templated, not retyped. A ``value`` evidence entry names one
value in a results file, and the question's text can refer to it with
Python format syntax, ``"about {improvement:.1f}x"``; the text is rendered
from the file whenever it is shown, so a number in an answer is always the
pipeline's own.

What can go wrong, worst first: the evidence isn't there at all (never run,
never pushed, or pinned to a Git ref that doesn't exist); a reference is
broken (a key that doesn't resolve, a placeholder that names no evidence, a
label missing from the LaTeX); the stage that produces it is out of date, so
what's on disk isn't what the project would produce now; or the stage is
frozen, or downstream of one, in which case the pipeline will never call it
out of date however far its inputs have moved -- and only a ``git_ref`` on
the citation says which version is meant.

Evidence pinned with ``git_ref`` is checked at that ref rather than in the
working tree. A pin is a claim about one version, so nothing about the
current pipeline can make it stale; what can go wrong is the ref or the
path not being there.

Git history is read for context, not for a verdict: when a cited value
changed after the commit that last edited the question, the report says so
and what it was, since that is worth a reader's attention. It is not a
failure -- prose can stay true while a number moves, and a templated number
updates itself.
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

EvidenceStatus = Literal[
    "ok",
    "changed",
    "missing",
    "stale",
    "frozen",
    "error",
    "skipped",
    "unattributed",
]
QuestionStatus = Literal[
    "ok",
    "stale",
    "frozen",
    "missing",
    "error",
    "unanswered",
    "no-evidence",
]
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
    #: The Git ref this citation pins itself to, if any
    git_ref: str | None = None


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
        """Answers whose evidence the pipeline would rebuild."""
        return [q for q in self.questions if q.status == "stale"]

    @property
    def frozen(self) -> list[QuestionCheck]:
        """Answers resting on a frozen stage, with no ref pinning them."""
        return [q for q in self.questions if q.status == "frozen"]

    @property
    def missing(self) -> list[QuestionCheck]:
        """Answers citing evidence that isn't there."""
        return [q for q in self.questions if q.status == "missing"]

    @property
    def errors(self) -> list[QuestionCheck]:
        return [q for q in self.questions if q.status == "error"]

    @property
    def answered(self) -> list[QuestionCheck]:
        return [q for q in self.questions if q.answered]

    @property
    def changed(self) -> list[EvidenceCheck]:
        """Evidence that moved after the question was last edited.

        Context rather than a verdict: a number can change without making
        the sentence around it wrong, and a templated one rewrites itself.
        """
        return [
            ev
            for q in self.questions
            for ev in q.evidence
            if ev.status == "changed"
        ]

    @property
    def ok(self) -> bool:
        """True if no answered question is missing, stale, or broken.

        Frozen evidence doesn't fail the check: nothing can be re-run to fix
        it, and whether a pin is wanted is the author's call.
        """
        return not self.missing and not self.stale and not self.errors

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


def parse_evidence_text(text: str, path: str) -> Any:
    """Parse the contents of a results file, by the extension of ``path``."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml"):
        return calkit.ryaml.load(text)
    if ext == ".json":
        return json.loads(text)
    if ext == ".toml":
        import tomllib

        return tomllib.loads(text)
    raise ValueError(
        f"Cannot read a value from {path}: only JSON, YAML, and TOML "
        "results files are supported"
    )


def read_evidence_file(path: str) -> Any:
    """Read a results file, by extension."""
    with open(path, encoding="utf-8") as f:
        return parse_evidence_text(f.read(), path)


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

    def __init__(self, repo: Any, wdir: str) -> None:
        self.repo = repo
        self.rel = os.path.relpath(
            os.path.join(wdir, CALKIT_YAML), str(repo.working_dir)
        ).replace(os.sep, "/")
        self._shas: list[str] | None = None
        self._parsed: dict[str, dict | None] = {}

    @property
    def shas(self) -> list[str]:
        """Commits that touched the file, newest first."""
        if self._shas is None:
            try:
                self._shas = str(
                    self.repo.git.log("--format=%H", "--", self.rel)
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


def _is_attributed(
    path: str, stage: str | None, ck_info: dict, wdir: str
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
    try:
        with open(os.path.join(wdir, "dvc.lock"), encoding="utf-8") as f:
            if _lock_hash(f.read(), path) is not None:
                return True
    except OSError:
        pass
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


def _declared_git_ref(ev: dict) -> str | None:
    """The ``git_ref`` an evidence entry declares, as a string.

    calkit.yaml is hand-written, and YAML reads an all-digit short SHA as an
    int. That's still a ref, so coerce rather than refusing it.
    """
    git_ref = ev.get("git_ref")
    if git_ref is None or git_ref == "":
        return None
    return git_ref if isinstance(git_ref, str) else str(git_ref)


def _read_at_ref(repo: Any, git_ref: str, path: str) -> str | None:
    """The text of ``path`` at ``git_ref``, or None if it isn't there."""
    try:
        return str(repo.git.show(f"{git_ref}:{path}"))
    except Exception:
        return None


def check_pinned_evidence(
    out: EvidenceCheck, ev: dict, repo: Any, wdir: str
) -> EvidenceCheck:
    """Check evidence pinned to a Git ref, at that ref.

    A pin is a claim about one version of an artifact, so the working tree
    and the current pipeline have nothing to say about it -- only whether
    the ref and the path are there, and whether a cited value still reads.
    A DVC-tracked path won't be in the tree at all; the lock naming it is as
    much as can be checked without fetching the content.
    """
    git_ref = out.git_ref or ""
    if repo is None:
        out.status = "skipped"
        out.message = f"no repo to resolve {git_ref} against"
        return out
    try:
        repo.commit(git_ref)
    except Exception:
        out.status = "missing"
        out.message = f"Git ref {git_ref!r} was not found; push it or fix it"
        return out
    text = _read_at_ref(repo, git_ref, out.path)
    if text is None:
        lock = _read_at_ref(repo, git_ref, "dvc.lock")
        if lock is not None and _lock_hash(lock, out.path) is not None:
            # Tracked by DVC at that commit: present, but its content lives
            # in storage, so a cited value can't be read from here.
            if is_value_evidence(ev):
                out.status = "skipped"
                out.message = (
                    f"DVC-tracked at {git_ref}; value not read from storage"
                )
            return out
        out.status = "missing"
        out.message = f"not found at {git_ref}; run the pipeline or push it"
        return out
    if is_value_evidence(ev):
        try:
            out.current = resolve_key(
                parse_evidence_text(text, out.path), out.key or ""
            )
        except KeyError:
            out.status = "error"
            out.message = (
                f"key {out.key!r} not found in {out.path} at {git_ref}"
            )
        except Exception as e:
            out.status = "error"
            out.message = (
                f"cannot read {out.path} at {git_ref}: "
                f"{e.__class__.__name__}: {e}"
            )
    return out


def check_evidence(
    ev: dict,
    ck_info: dict,
    wdir: str,
    repo: Any,
    since: str | None,
    stale_stages: set[str] | None = None,
    frozen_stages: set[str] | None = None,
) -> EvidenceCheck:
    """Check one evidence entry against the working tree and history.

    ``stale_stages`` and ``frozen_stages`` are base stage names from the
    pipeline: the ones DVC would re-run, and the ones it never will because
    they're frozen or downstream of a freeze.
    """
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
        git_ref=_declared_git_ref(ev),
    )
    if not path:
        out.status = "error"
        out.message = "evidence has no path"
        return out
    if out.git_ref is not None:
        return check_pinned_evidence(out, ev, repo, wdir)
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
            # Not overwritten: a deprecated entry that also changed is
            # still worth migrating, and the hint is the only place it is
            # said
            out.message = "; ".join(filter(None, [out.message, change]))
    base = (out.stage or "").split("@")[0]
    if out.status in ("ok", "changed") and base:
        if base in (stale_stages or set()):
            out.status = "stale"
            out.message = "; ".join(
                filter(
                    None,
                    [
                        out.message,
                        f"stage '{base}' is out of date; run the pipeline",
                    ],
                )
            )
        elif base in (frozen_stages or set()):
            out.status = "frozen"
            out.message = "; ".join(
                filter(
                    None,
                    [
                        out.message,
                        f"stage '{base}' is frozen, or downstream of one, so "
                        "nothing will report it out of date; cite a git_ref "
                        "to pin which version this is",
                    ],
                )
            )
    if out.status == "ok" and not _is_attributed(
        path, out.stage, ck_info, wdir
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
    wdir: str,
    repo: Any = None,
    history: CalkitYamlHistory | None = None,
    stale_stages: set[str] | None = None,
    frozen_stages: set[str] | None = None,
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
        question_commit(question, repo, wdir, history)
        if repo is not None
        else None
    )
    checks = [
        check_evidence(
            ev,
            ck_info,
            wdir,
            repo,
            since,
            stale_stages=stale_stages,
            frozen_stages=frozen_stages,
        )
        for ev in evidence
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
    # Worst first, matching what the hub shows against each question: an
    # answer resting on nothing anyone can find is worse off than one
    # resting on something merely out of date.
    statuses = {c.status for c in checks}
    status: QuestionStatus = "ok"
    if "missing" in statuses:
        status = "missing"
    elif messages or "error" in statuses:
        status = "error"
    elif "stale" in statuses:
        status = "stale"
    elif "frozen" in statuses:
        status = "frozen"
    if "changed" in statuses:
        # Said either way, since it is the one thing here that asks for a
        # reader rather than a command.
        messages.append(
            "evidence changed since the answer was last edited; worth "
            "re-reading, and editing the question if it no longer holds"
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


def pipeline_stage_sets(
    ck_info: dict, wdir: str, check_pipeline: bool = True
) -> tuple[set[str], set[str]]:
    """The stages that are out of date, and the ones frozen out of reach.

    Best-effort: a pipeline that can't be read leaves both empty rather than
    failing the whole check, since most of what it reports doesn't depend on
    the pipeline at all.
    """
    from calkit.pipeline import frozen_tainted_stage_names, get_status

    if not check_pipeline:
        return set(), set()
    stale: set[str] = set()
    frozen: set[str] = set()
    try:
        status = get_status(
            ck_info=ck_info,
            wdir=wdir,
            check_environments=False,
            clean_notebooks=False,
            compile_to_dvc=False,
        )
        stale = {n.split("@")[0] for n in status.stale_stage_names}
    except Exception:
        pass
    try:
        frozen = frozen_tainted_stage_names(ck_info=ck_info, wdir=wdir)
    except Exception:
        pass
    return stale, frozen


def check_questions(
    ck_info: dict | None = None,
    wdir: str | None = None,
    check_pipeline: bool = True,
) -> QuestionsStatus:
    """Check every question in a project against its evidence.

    ``check_pipeline`` asks DVC which stages are out of date, which is the
    slowest thing here; turning it off skips that and the frozen check with
    it, leaving the rest of the report intact.
    """
    wdir = wdir or os.getcwd()
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    try:
        repo = calkit.git.get_repo(wdir)
    except Exception:
        repo = None
    questions = ck_info.get("questions", []) or []
    # One reading of calkit.yaml's history, and one of the pipeline, for all
    # of them
    history = CalkitYamlHistory(repo, wdir) if repo is not None else None
    stale_stages, frozen_stages = pipeline_stage_sets(
        ck_info, wdir, check_pipeline
    )
    return QuestionsStatus(
        questions=[
            check_question(
                n,
                q,
                ck_info,
                wdir,
                repo,
                history,
                stale_stages=stale_stages,
                frozen_stages=frozen_stages,
            )
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
        needs_attention = q.status in (
            "missing",
            "error",
            "stale",
            "frozen",
        ) or any(ev.status in ("unattributed", "changed") for ev in q.evidence)
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
            f"Answers backed by current evidence: {n_ok}/{len(answered)} "
            f"{calkit.check_or_x(n_ok == len(answered))}"
        )
        lines.append(
            f"Answers citing evidence that isn't there: "
            f"{len(status.missing)} {calkit.check_or_x(not status.missing)}"
        )
        lines.append(
            f"Answers with broken references: {len(status.errors)} "
            f"{calkit.check_or_x(not status.errors)}"
        )
        lines.append(
            f"Answers whose evidence the pipeline would rebuild: "
            f"{len(status.stale)} {calkit.check_or_x(not status.stale)}"
        )
    # No check mark either way on the rest: worth a look, not a verdict
    if status.frozen:
        lines.append(
            f"Answers resting on a frozen stage, unpinned: "
            f"{len(status.frozen)} (worth a look)"
        )
    no_evidence = sum(1 for q in answered if q.status == "no-evidence")
    if no_evidence:
        lines.append(
            f"Answers given without evidence: {no_evidence} (worth a look)"
        )
    if status.changed:
        lines.append(
            f"Evidence that changed after the answer was written: "
            f"{len(status.changed)} (worth a look)"
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
