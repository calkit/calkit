"""CLI for showing objects."""

from __future__ import annotations

import json
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
                "numbers it, or its name; prefix a subproject's with its "
                "path, e.g., 'sub:1'."
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
        format_lines,
        get_evidence_kind,
        placeholders,
        question_index,
        render_question,
    )

    def evidence_line(ev: dict, c: EvidenceCheck | None) -> list[str]:
        kind = get_evidence_kind(ev)
        line = f"- {(kind or 'file').capitalize()} `{ev.get('path', '')}`"
        if kind is None and ev.get("lines") is not None:
            try:
                line += f", {format_lines(ev['lines'])}"
            except ValueError:
                # The check reports a malformed range
                line += f", lines {ev['lines']}"
        sub = []
        key = ev.get("key")
        # A value without a key is an error the check reports
        if key and kind in ("value", "result"):
            name = ev.get("name")
            if name and name != key:
                line += f" as `{name}`"
            line += f" at `{key}`"
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

    # A subproject's question is addressed as 'calkit list questions' shows
    # it, e.g., 'sub:1'
    wdir, ref = ".", question
    prefix, sep, rest = question.rpartition(":")
    projects = (
        {Path(w).as_posix(): info for w, info in calkit.iter_projects()}
        if sep
        else {}
    )
    if sep and Path(prefix).as_posix() in set(projects) - {"."}:
        wdir, ref = Path(prefix).as_posix(), rest
    ck_info = projects.get(wdir) or calkit.load_calkit_info()
    questions = ck_info.get("questions") or []
    try:
        index = question_index(questions, ref)
    except ValueError as e:
        raise_error(str(e))
    entry = questions[index]
    shown = entry if raw else render_question(entry, ck_info, wdir=wdir)
    fields = dict(shown) if isinstance(shown, dict) else {"question": shown}
    check = check_questions(
        ck_info, wdir=wdir, check_pipeline=False, only=index + 1
    ).questions[0]
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
    where = f"{wdir}: " if wdir != "." else ""
    lines = [
        f"# {where}{index + 1}. {out['question']}",
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


@show_app.command(name="table|tbl")
def show_table(
    path: Annotated[str, typer.Argument(help="Path to the table.")],
    columns: Annotated[
        list[str] | None,
        typer.Option(
            "--column",
            "-c",
            help="Only show these columns, in this order. Can be a glob, "
            "e.g., `*_mod`, and can be given more than once.",
        ),
    ] = None,
    filters: Annotated[
        list[str] | None,
        typer.Option(
            "--filter",
            "-f",
            help="Only show rows matching COLUMN=VALUE, COLUMN~TEXT "
            "(contains, ignoring case), or COLUMN>NUMBER. Can be given "
            "more than once, and all must match.",
        ),
    ] = None,
    rows: Annotated[
        str | None,
        typer.Option(
            "--rows",
            "-r",
            help="Only show these rows, 1-based, e.g., '1-20', '5,9', '40-'.",
        ),
    ] = None,
    head: Annotated[
        int | None,
        typer.Option(
            "--head", "-n", min=0, help="Only show the first N rows."
        ),
    ] = None,
    tail: Annotated[
        int | None,
        typer.Option("--tail", min=0, help="Only show the last N rows."),
    ] = None,
    git_ref: Annotated[
        str | None,
        typer.Option(
            "--git-ref",
            help="Show the table as of this Git branch, tag, or commit "
            "instead of the working tree.",
        ),
    ] = None,
    status: Annotated[
        bool,
        typer.Option(
            "--status",
            "-s",
            help="Also say whether the table is up to date.",
        ),
    ] = False,
    vscode: Annotated[
        bool,
        typer.Option(
            "--vscode",
            help="Open the table in VS Code instead of printing it.",
        ),
    ] = False,
    engine: Annotated[
        str | None,
        typer.Option(
            "--engine",
            help="Dataframe engine for formats the standard library can't "
            "read, e.g., Parquet. Defaults to the configured one.",
        ),
    ] = None,
) -> None:
    """Show a table, or part of one.

    With --status, says whether the stage that writes the table has been
    run since its inputs last changed. At a --git-ref that's reconstructed
    from the dvc.lock committed there, since there is nothing on disk at an
    old commit for DVC to hash, and what it couldn't check is reported
    rather than assumed current.
    """
    import calkit.pipeline
    import calkit.tables

    content = None
    if git_ref is not None:
        try:
            content = calkit.pipeline.read_artifact_at_ref(path, git_ref)
        except FileNotFoundError as e:
            raise_error(str(e))
    elif not os.path.isfile(path):
        raise_error(
            f"{path} does not exist; see 'calkit list tables' for what the "
            "project has"
        )
    if status:
        _echo_artifact_status(path, git_ref)
    if vscode:
        _open_in_vscode(path, git_ref, content)
        return
    selected = [
        name.strip()
        for value in columns or []
        for name in value.split(",")
        if name.strip()
    ]
    try:
        table = calkit.tables.read_table(
            path,
            content=content,
            columns=selected or None,
            filters=filters,
            rows=rows,
            head=head,
            tail=tail,
            engine=engine,  # type: ignore[arg-type]
        )
    except (ValueError, ImportError) as e:
        raise_error(str(e))
    from rich import box
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    names, values = table["columns"], table["rows"]
    # Named on its own line rather than as the table's title, which a
    # narrow table wraps a character at a time
    typer.echo(path + (f" @ {git_ref}" if git_ref else ""))
    rendered = Table(header_style="bold", box=box.SIMPLE, pad_edge=False)
    for i, name in enumerate(names):
        # Right-align a column whose every value is a number, so figures
        # line up on the decimal point
        filled = [row[i] for row in values if row[i] != ""]
        numeric = bool(filled) and all(_is_number(v) for v in filled)
        # Escaped so text in brackets, e.g., units, isn't read as markup
        rendered.add_column(
            escape(name), justify="right" if numeric else "left"
        )
    for row in values:
        rendered.add_row(*(escape(v) for v in row))
    console = Console()
    squeezed = console.measure(rendered).maximum > console.width
    console.print(rendered)
    shown = len(values)
    matching, total = table["n_rows_matching"], table["n_rows"]
    if shown != total:
        line = f"{shown} of {total} rows"
        if matching != total:
            line += f", {matching} matching the filter"
        typer.echo(line)
    if squeezed:
        typer.echo(
            f"{len(names)} columns don't fit; name the ones you want with "
            "-c, which takes globs, e.g., -c '*_mod'"
        )


def _echo_artifact_status(
    path: str, git_ref: str | None, err: bool = False
) -> None:
    # Written to stderr when stdout is for machine-readable output
    import calkit.pipeline

    if git_ref is not None:
        try:
            state = calkit.pipeline.artifact_status_at_ref(path, git_ref)
        except FileNotFoundError as e:
            warn(str(e), err=err)
            return
        line = f"{state['status']} at {git_ref}"
        if state["unverifiable"]:
            line += f" ({state['unverifiable']} input(s) not checkable)"
        typer.echo(line, err=err)
        for reason in state["reasons"]:
            typer.echo(f"  {reason}", err=err)
        return
    norm = Path(os.path.normpath(path)).as_posix()
    try:
        annotated = calkit.pipeline.annotate_artifacts(
            [{"path": norm}], status=True
        )[0]
    except RuntimeError as e:
        warn(f"Failed to determine status: {e}", err=err)
        return
    stages = ", ".join(annotated.get("stages") or [])
    typer.echo(
        annotated["status"] + (f" (stage: {stages})" if stages else ""),
        err=err,
    )


def _open_in_vscode(
    path: str, git_ref: str | None, content: bytes | None
) -> None:
    import tempfile

    code = shutil.which("code")
    if code is None:
        raise_error(
            "The 'code' command isn't on PATH; install VS Code's shell "
            "command from its command palette"
        )
    target = path
    if content is not None:
        # The ref's contents aren't on disk, so give the editor a file
        # named for what it holds
        stem, ext = os.path.splitext(os.path.basename(path))
        safe_ref = git_ref.replace("/", "-") if git_ref else "ref"
        target = os.path.join(
            tempfile.mkdtemp(prefix="calkit-table-"),
            f"{stem}@{safe_ref}{ext}",
        )
        with open(target, "wb") as f:
            f.write(content)
    subprocess.call([code, target])


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


@show_app.command(name="result|res")
def show_result(
    path: Annotated[str, typer.Argument(help="Path to the result.")],
    keys: Annotated[
        list[str] | None,
        typer.Option(
            "--key",
            "-k",
            help="Only show these keys, dotted as a question's evidence "
            "writes them, e.g., `steady_state.saved_pct`. Can be given "
            "more than once.",
        ),
    ] = None,
    depth: Annotated[
        int | None,
        typer.Option(
            "--depth",
            "-d",
            help="Stop flattening this many levels in and show the rest "
            "of each value as JSON.",
        ),
    ] = None,
    git_ref: Annotated[
        str | None,
        typer.Option(
            "--git-ref",
            help="Show the result as of this Git branch, tag, or commit "
            "instead of the working tree.",
        ),
    ] = None,
    status: Annotated[
        bool,
        typer.Option(
            "--status",
            "-s",
            help="Also say whether the result is up to date.",
        ),
    ] = False,
    vscode: Annotated[
        bool,
        typer.Option(
            "--vscode",
            help="Open the result in VS Code instead of printing it.",
        ),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
) -> None:
    """Show a result's keys and values.

    Keys are shown dotted, the way a question's value evidence names them,
    so what's printed is what an answer can cite. With --status, says
    whether the stage that writes the result has been run since its inputs
    last changed.
    """
    import calkit.pipeline
    import calkit.results

    content = None
    if git_ref is not None:
        try:
            content = calkit.pipeline.read_artifact_at_ref(path, git_ref)
        except FileNotFoundError as e:
            raise_error(str(e))
    elif not os.path.isfile(path):
        raise_error(
            f"{path} does not exist; see 'calkit list results' for what the "
            "project has"
        )
    if status:
        _echo_artifact_status(path, git_ref, err=json_output)
    if vscode:
        _open_in_vscode(path, git_ref, content)
        return
    selected = [
        key.strip()
        for value in keys or []
        for key in value.split(",")
        if key.strip()
    ]
    try:
        result = calkit.results.read_result(
            path, content=content, keys=selected or None, depth=depth
        )
    except ValueError as e:
        raise_error(str(e))
    if json_output:
        echo_json(result["items"])
        return
    from rich import box
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    typer.echo(path + (f" @ {git_ref}" if git_ref else ""))
    rendered = Table(header_style="bold", box=box.SIMPLE, pad_edge=False)
    rendered.add_column("key")
    numeric = all(
        _is_number(item["value"])
        for item in result["items"]
        if item["value"] != ""
    )
    rendered.add_column("value", justify="right" if numeric else "left")
    for item in result["items"]:
        rendered.add_row(escape(item["key"]), escape(item["value"]))
    Console().print(rendered)


@show_app.command(name="provenance|prov")
def show_provenance(
    path: Annotated[
        str,
        typer.Argument(
            help="Path to what to trace, e.g., a figure, table, results "
            "file, or notebook whose saved value to trace."
        ),
    ],
    key: Annotated[
        str | None,
        typer.Option(
            "--key",
            "-k",
            help="Trace one value in a results file, dotted as a "
            "question's evidence writes it, e.g., `fit.rmse`, or one a "
            "notebook's cells save.",
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
) -> None:
    """Show how a file or value was made, back to where its data came from.

    This answers "How did you calculate it?" from the project rather than
    from memory: whether it's up to date, and if not, why; the stage that
    makes it, with its source or command, environment, and last run; and
    its inputs. Then the same for each stage upstream, nearest first, down
    to raw data, imports, and anything whose origin isn't defined.
    """
    import posixpath

    import calkit
    import calkit.pipeline
    import calkit.provenance
    import calkit.results

    def describe_input(inp: dict) -> str:
        notes = []
        if inp["stage"] is not None:
            notes.append(f"from stage {inp['stage']}")
            if inp["copied_from"]:
                notes.append(
                    f"copied from {inp['copied_from']} by stage "
                    f"{inp['copy_stage']}"
                )
        elif inp["origin"]:
            url = inp["origin_url"]
            notes.append(
                inp["origin"]
                + (f" ({url})" if url and url not in inp["origin"] else "")
            )
        for gap in inp["gaps"]:
            what = (
                "imported from somewhere that can't be checked"
                if gap["unchecked"]
                else "origin not defined"
            )
            notes.append(
                what
                + (f" for {gap['path']}" if gap["path"] != inp["path"] else "")
            )
        if inp["removed"]:
            notes.append("no longer an input")
        elif inp["new"]:
            notes.append("new since last run")
        elif not inp["exists"]:
            notes.append("missing")
        elif not inp["on_disk"]:
            notes.append("not pulled")
        elif inp["modified"]:
            notes.append("modified")
        return str(inp["path"]) + (": " + "; ".join(notes) if notes else "")

    def get_stage_state(stage: dict) -> list[str]:
        # What's wrong with a stage, if anything, in its own words
        status = stage["status"]
        if status is None:
            return []
        name = stage["name"]
        lines = []
        if stage["frozen_changes"] is not None:
            changed = ", ".join(stage["frozen_changes"])
            lines.append(
                "Frozen: inputs changed since its outputs were made"
                + (f" ({changed})" if changed else "")
                + f"; only `calkit run {name.split('@')[0]} --force` "
                "remakes them"
            )
        if status.get("status") == "not-run":
            lines.append(f"Out of date: stage {name} not run")
        elif status.get("status") == "stale":
            new = {i["path"] for i in stage["inputs"] if i["new"]}
            reasons = [
                f"{p} new since last run" if p in new else f"{p} modified"
                for p in status.get("modified_inputs") or []
            ]
            if status.get("modified_command"):
                reasons.append("command modified")
            reasons += [
                f"{p} modified outside pipeline"
                for p in status.get("modified_outputs") or []
            ]
            if reasons:
                lines.append("Out of date: " + ", ".join(reasons))
            if stage["missing"]:
                lines.append(
                    "Missing: "
                    + ", ".join(stage["missing"])
                    + (
                        ""
                        if reasons
                        else "; `calkit pull` may be all it needs"
                    )
                )
            if not reasons and not stage["missing"]:
                lines.append("Out of date")
        if stage["waiting_on"]:
            lines.append(
                "Out of date: waiting on " + ", ".join(stage["waiting_on"])
            )
        if stage["after_frozen"]:
            lines.append(
                "Out of date: made from outputs of frozen stage"
                + ("s " if len(stage["after_frozen"]) > 1 else " ")
                + ", ".join(stage["after_frozen"])
                + ", which `calkit run` won't remake without --force"
            )
        return lines

    def get_last_run_text(stage: dict) -> str | None:
        run = stage["last_run"]
        if run is None:
            if (stage["status"] or {}).get("status") == "not-run":
                return None
            if stage["frozen"]:
                return "not recorded; frozen, so `calkit run` skips it"
            return "not recorded"
        system = run.get("system") or {}
        agent = run.get("agent")
        if isinstance(agent, dict):
            agent = agent.get("name")
        start = str(run.get("start_time") or "")[:16].replace("T", " ")
        parts = [
            f"{start} UTC" if start else "",
            " ".join(
                str(system[k]) for k in ("os", "machine") if system.get(k)
            ),
            f"after commit {run['git_rev'][:7]}" if run.get("git_rev") else "",
            f"by {agent}" if agent else "",
        ]
        return ", ".join(p for p in parts if p)

    def get_environment_text(env: dict) -> str:
        if env["name"] == "_system":
            return "_system, i.e., this machine as is"
        details = ", ".join(e for e in (env["kind"], env["path"]) if e)
        text = str(env["name"]) + (f" ({details})" if details else "")
        if env["lock_path"]:
            text += f", locked in {env['lock_path']}"
        return text

    # The project is the nearest folder up with a calkit.yaml, and paths are
    # relative to it, as the pipeline names them
    root = os.getcwd()
    while not os.path.isfile(os.path.join(root, "calkit.yaml")):
        if os.path.dirname(root) == root:
            raise_error("Not in a Calkit project")
        root = os.path.dirname(root)
    try:
        rel_path = Path(
            os.path.relpath(os.path.abspath(path), root)
        ).as_posix()
    except ValueError:
        # E.g., on another drive
        raise_error(f"{path} isn't in this project")
    rel_path = posixpath.normpath(rel_path)
    if rel_path == ".." or rel_path.startswith("../"):
        raise_error(f"{path} isn't in this project")
    try:
        stage_runs = calkit.read_stage_runs(root)
    except ValueError:
        warn(
            "Couldn't read .calkit/stage-runs.json, so last runs aren't "
            "shown; see 'calkit check stage-runs'",
            err=json_output,
        )
        stage_runs = {}
    try:
        pipeline = calkit.pipeline.get_summary(root)
    except Exception as e:
        raise_error(f"Failed to determine pipeline status: {e}")
    args = calkit.provenance.get_checkout_args(root, pipeline)
    frozen_changes = pipeline.get("frozen_changes")
    # Statuses read while that failed would all say up to date
    if pipeline["error"]:
        warn(
            f"Couldn't check whether it's up to date: {pipeline['error']}",
            err=True,
        )
        args |= {"stage_statuses": {}, "frozen": set()}
        frozen_changes = None
    chain = calkit.provenance.get_provenance_chain(
        rel_path,
        key=key,
        stage_runs=stage_runs,
        frozen_changes=frozen_changes,
        **args,
    )
    if not chain["exists"] and chain["stage"] is None and not chain["origin"]:
        raise_error(f"{rel_path} isn't in the project, and no stage makes it")
    if key is not None and chain["value_error"] and chain["on_disk"]:
        # Saying which keys there are, as 'calkit show result' does
        try:
            calkit.results.read_result(
                os.path.relpath(os.path.join(root, chain["path"])),
                keys=[key],
            )
        except Exception as e:
            raise_error(str(e))
        raise_error(chain["value_error"])
    if json_output:
        echo_json(chain | {"status_error": pipeline["error"]})
        return
    lines = [
        chain["path"]
        if chain["path"] == rel_path
        else f"{rel_path} (saved in {chain['path']})"
    ]
    if key is not None:
        lines.append(
            f"{key}: {chain['value_error']}"
            if chain["value_error"]
            else f"{key} = {json.dumps(chain['value'])}"
        )
    if chain["copied_from"]:
        lines.append(
            f"Copied from {chain['copied_from']} by stage "
            f"{chain['copy_stage']}"
        )
    own = chain["stages"][0] if chain["stage"] is not None else None
    if chain["up_to_date"]:
        lines.append("Up to date")
    elif chain["up_to_date"] is False:
        state = get_stage_state(own) if own is not None else []
        if not state and chain["stale_reason"] and chain["copy_stage"]:
            state = [f"Out of date: stage {chain['copy_stage']} out of date"]
        lines += state or ["Out of date" if chain["exists"] else "Missing"]
    elif own is not None or chain["copy_stage"]:
        lines.append("Status unknown")
    if chain["stage"] is None:
        if chain["origin"]:
            url = chain["origin_url"]
            lines.append(
                chain["origin"]
                + (f" ({url})" if url and url not in chain["origin"] else "")
            )
        lines += [
            (
                "Imported from somewhere that can't be checked: "
                if g["unchecked"]
                else "Origin not defined: "
            )
            + g["path"]
            for g in chain["gaps"]
        ]
        if chain["source_of"]:
            lines.append("Source of stage " + ", ".join(chain["source_of"]))
        readers = [
            s for s in chain["input_to_stages"] if s not in chain["source_of"]
        ]
        if readers:
            lines.append("Read by stage " + ", ".join(readers))
        if not (
            chain["origin"]
            or chain["gaps"]
            or chain["source_of"]
            or readers
            or chain["copy_stage"]
        ):
            lines.append("No stage makes it")
    typer.echo("\n".join(lines))
    for stage in chain["stages"]:
        lines = [
            typer.style(f"Stage {stage['name']}", bold=True)
            + (f" ({stage['kind']})" if stage["kind"] else "")
        ]
        lines.append("  Makes: " + ", ".join(stage["makes"]))
        if stage["source"]:
            lines.append(f"  Source: {stage['source']}")
        command = stage["command"]
        # An iteration's, with its values filled in
        if "@" in stage["name"] and stage["lock_command"]:
            command = stage["lock_command"]
            if isinstance(command, list):
                command = " && ".join(command)
        if command:
            lines.append(f"  Command: {command}")
        if stage["message"]:
            lines.append(f"  Step: {stage['message']}")
        for env in stage["environments"]:
            lines.append("  Environment: " + get_environment_text(env))
        last_run = get_last_run_text(stage)
        if last_run:
            lines.append(f"  Last run: {last_run}")
        # The path's own stage's state is the one said first
        if stage["depth"]:
            lines += [f"  {line}" for line in get_stage_state(stage)]
        lines.append("  Inputs:" if stage["inputs"] else "  Inputs: none")
        lines += [f"    {describe_input(inp)}" for inp in stage["inputs"]]
        typer.echo("\n" + "\n".join(lines))
