"""CLI for showing objects."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from calkit.cli import AliasGroup, echo_json, raise_error, warn

show_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


@show_app.command(name="question|q")
def show_question(
    question: Annotated[
        str,
        typer.Argument(
            help=(
                "The question's 1-based position, as 'calkit list questions' "
                "numbers it, or its name."
            )
        ),
    ],
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="Show the text as written, with its {name} placeholders, "
            "instead of rendered from the evidence.",
        ),
    ] = False,
) -> None:
    """Show a question in full as Markdown, with its evidence and sign-offs.

    Placeholders in the text, such as ``{improvement:.1f}``, are filled from
    the question's value evidence, so numbers shown are read from the
    results files rather than retyped into ``calkit.yaml``. The pipeline
    stages behind its evidence are shown too, upstream first.
    """
    import calkit
    from calkit.questions import (
        TEMPLATED_FIELDS,
        EvidenceCheck,
        SignOffCheck,
        check_questions,
        format_letters,
        placeholders,
        question_index,
        render_question,
    )

    def evidence_line(ev: dict, c: EvidenceCheck | None) -> list[str]:
        kind = ev.get("kind", "result")
        line = f"- {kind.capitalize()} `{ev.get('path', '')}`"
        sub = []
        if kind == "value" or (kind == "result" and ev.get("key")):
            name = ev.get("name")
            if name and name != ev["key"]:
                line += f" as `{name}`"
            line += f" at `{ev['key']}`"
            if c is not None and c.current is not None:
                line += f" = {c.current}"
        for name, key in (ev.get("values") or {}).items():
            value = (c.values or {}).get(name) if c is not None else None
            sub.append(
                f"  - `{name}` at `{key}`"
                + (f" = {value}" if value is not None else "")
            )
        if ev.get("section"):
            line += f", section {ev['section']}"
        if ev.get("label"):
            line += f" (`{ev['label']}`)"
        if ev.get("git_ref"):
            line += f", pinned to `{ev['git_ref']}`"
        if ev.get("explanation"):
            line += f": {ev['explanation']}"
        if c is not None and c.status not in ("ok", "skipped"):
            line += f" *({c.status}" + (f": {c.message}" if c.message else "")
            line += ")*"
        return [line] + sub

    def sign_off_line(c: SignOffCheck) -> str:
        line = "- " + c.by
        if c.with_ai:
            line += f" (with {', '.join(c.with_ai)})"
        if c.date:
            line += f", {c.date}"
        line += f" *({c.status}" + (f": {c.message}" if c.message else "")
        line += ")*"
        return line + (f": {c.notes}" if c.notes else "")

    def text(value: object) -> str:
        # A conditional answer left in its branches lists them
        if not isinstance(value, dict):
            return str(value)
        lines = []
        for clause, branch in value.items():
            word, _, condition = str(clause).partition(" ")
            cond = f" `{condition}`" if condition else ""
            lines.append(f"- **{word}**{cond}: {branch}")
        return "\n".join(lines)

    ck_info = calkit.load_calkit_info()
    questions = ck_info.get("questions") or []
    try:
        index = question_index(questions, question)
    except ValueError as e:
        raise_error(str(e))
    entry = questions[index]
    shown = entry if raw else render_question(entry, ck_info)
    fields = dict(shown) if isinstance(shown, dict) else {"question": shown}
    check = next(
        c
        for c in check_questions(ck_info, check_pipeline=False).questions
        if c.project is None and c.index == index + 1
    )
    # A placeholder left as written looks exactly like text somebody meant
    # literally, so say when one couldn't be filled. A conditional answer
    # still in clauses is one whose conditions couldn't be read.
    texts = [fields.get(f) or "" for f in TEMPLATED_FIELDS] + [
        ev.get("explanation") or ""
        for ev in fields.get("evidence") or []
        if isinstance(ev, dict)
    ]
    if not raw and any(isinstance(t, dict) or placeholders(t) for t in texts):
        warn(
            "Some placeholders or conditions could not be filled from the "
            "evidence. Run 'calkit check questions' to see why; 'calkit pull' "
            "if the results files are not here yet.",
            err=True,
        )
    # The stages are derived, so shown ahead of the answer but never written
    out: dict = {}
    for k, v in fields.items():
        if k == "answer" and check.stages:
            out["stages"] = check.stages
        out[k] = v
    if check.stages:
        out.setdefault("stages", check.stages)
    if json_output:
        echo_json({**out, "check": check.model_dump(mode="json")})
        return
    lines = [
        f"# {index + 1}. {out['question']}",
        f"`{format_letters(check)}`",
    ]
    for k, v in out.items():
        if k == "stages":
            lines.append("**Stages:** " + ", ".join(f"`{s}`" for s in v))
        elif k == "name":
            lines.append(f"**Name:** `{v}`")
        elif k in ("hypothesis", "approach", "answer") and v is not None:
            sep = "\n\n" if isinstance(v, dict) else " "
            lines.append(f"**{k.capitalize()}:**{sep}{text(v)}")
    evidence = [ev for ev in out.get("evidence") or [] if isinstance(ev, dict)]
    if evidence:
        checks: list = check.evidence or [None] * len(evidence)
        lines.append(
            "## Evidence\n\n"
            + "\n".join(
                "\n".join(evidence_line(ev, c))
                for ev, c in zip(evidence, checks)
            )
        )
    if out.get("notes"):
        lines.append(f"## Notes\n\n{text(out['notes'])}")
    for title, sign_offs in [
        ("Verifications", check.verifications),
        ("Validations", check.validations),
    ]:
        if sign_offs:
            lines.append(
                f"## {title}\n\n" + "\n".join(map(sign_off_line, sign_offs))
            )
    typer.echo("\n\n".join(lines))


@show_app.command(name="latex-diff")
def show_latex_diff(
    target: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Which diff: its stage or PDF, the document or its PDF, the "
                "latex stage, or the revision it compares against. Can be "
                "omitted if the project keeps only one."
            )
        ),
    ] = None,
    run: Annotated[
        bool,
        typer.Option(
            "--run", help="Build the diff first if it's stale or not built."
        ),
    ] = False,
) -> None:
    """Open a LaTeX diff the pipeline keeps.

    From VS Code's terminal it opens in the editor, otherwise in the
    system's PDF viewer.
    """
    import calkit.latex

    def norm(path: str) -> str:
        return Path(os.path.normpath(path)).as_posix()

    ck_info = calkit.load_calkit_info()
    try:
        diffs = calkit.latex.get_pipeline_diffs(ck_info, status=True)
    except RuntimeError as e:
        raise_error(f"Failed to determine diff status: {e}")
    if target is not None:
        diffs = [
            diff
            for diff in diffs
            if target in (diff["stage"], diff["latex_stage"], diff["from_ref"])
            or norm(target)
            in (
                diff["path"],
                diff["document"],
                norm(str(Path(diff["document"]).with_suffix(".pdf"))),
            )
        ]
    if not diffs:
        raise_error(
            "No LaTeX diff"
            + (f" matches '{target}'" if target is not None else "s are kept")
            + "; see 'calkit list latex-diffs'"
        )
    if len(diffs) > 1:
        names = ", ".join(diff["stage"] for diff in diffs)
        raise_error(f"More than one diff matches; name one of: {names}")
    diff = diffs[0]
    if diff["status"] != "up to date":
        if run:
            # Its own process, so the run reports what it did the usual way
            status = subprocess.call(
                [sys.executable, "-m", "calkit", "run", diff["stage"]]
            )
            if status:
                raise_error(f"Failed to build {diff['path']}")
        elif diff["status"] == "not built":
            raise_error(
                f"{diff['path']} hasn't been built; run 'calkit run "
                f"{diff['stage']}' or pass --run"
            )
        else:
            warn(
                f"{diff['path']} is stale; run 'calkit run {diff['stage']}' "
                "or pass --run to update it"
            )
    # The editor's CLI opens it in the window the terminal belongs to
    code = shutil.which("code")
    if os.environ.get("TERM_PROGRAM") == "vscode" and code is not None:
        subprocess.call([code, diff["path"]])
    else:
        typer.launch(diff["path"])
