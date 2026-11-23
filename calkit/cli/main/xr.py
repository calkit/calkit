"""The ``calkit xr`` command."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any

import typer

import calkit
from calkit.cli import raise_error, warn
from calkit.cli.main.core import (
    STAGE_RUNS_FPATH,
    app,
    init,
    project_is_initialized,
    run,
)


def _unstage_record(paths: list[str]) -> None:
    """Unstage what recorded a run, with what the run staged itself."""
    import git

    paths = [
        os.path.abspath(p)
        for p in [*paths, *calkit.environments.STAGED_CALKIT_PATHS]
    ]
    try:
        repo = git.Repo(search_parent_directories=True)
    except Exception:
        return
    if repo.head.is_valid():
        # Path by path, since restore errors out on a pathspec that matches
        # nothing---normal here, where some of these were never created
        for unstage_path in paths:
            try:
                repo.git.restore("--staged", "--", unstage_path)
            except Exception:
                pass
    else:
        # A just-created repo has no HEAD to restore the index from, and
        # also nothing tracked, so dropping the entries is right
        try:
            repo.git.rm("--cached", "-r", "--ignore-unmatch", "--", *paths)
        except Exception:
            pass


def _xr_markdown(
    markdown_path: str,
    ck_info: dict,
    environment: str | None,
    dry_run: bool,
    force: bool,
    verbose: bool,
    no_record: bool = False,
) -> None:
    """Bootstrap a runnable Markdown file into the pipeline, then run it.

    Unlike a script, a Markdown file declares however many stages its
    annotated blocks do, so this records one ``markdown`` stage standing
    in for them all. Environments the blocks don't name are detected from
    the code and written back into the annotations, which is the only
    place a per-stage environment can live.

    Nothing needs to exist beforehand: an ordinary README in an ordinary
    directory gets the project initialized around it, its code fences
    annotated, and an environment built from what those fences import.
    """
    import io
    import shutil

    import calkit.markdown

    def _snapshot(paths: list[str]) -> dict[str, bytes | None]:
        """Read files as they are now, so a failed run can put them back."""
        snap: dict[str, bytes | None] = {}
        for path in paths:
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    snap[path] = f.read()
            else:
                snap[path] = None
        return snap

    if not os.path.isfile(markdown_path):
        raise_error(f"{markdown_path} does not exist")
    markdown_path = Path(markdown_path).as_posix()
    with open(markdown_path, encoding="utf-8") as f:
        original_text = f.read()
    text = original_text
    try:
        doc = calkit.markdown.read_markdown(text, markdown_path)
    except Exception as e:
        raise_error(str(e))
    if not doc.stages:
        # A file nobody has marked up yet gets its runnable fences
        # annotated, which is how a plain README becomes a pipeline
        text, annotated = calkit.markdown.annotate_code_blocks(
            original_text, markdown_path
        )
        if annotated:
            typer.echo(
                f"Annotating code blocks in {markdown_path} as stage(s): "
                + ", ".join(sorted(annotated.stages))
            )
            if annotated.environments:
                typer.echo(
                    "Reading install commands as environment(s): "
                    + ", ".join(sorted(annotated.environments))
                )
            try:
                doc = calkit.markdown.read_markdown(text, markdown_path)
            except Exception as e:
                raise_error(str(e))
    if not doc.stages:
        raise_error(
            f"{markdown_path} declares no stages; annotate a code block "
            "with 'calkit stage name=<name>' to define one"
        )
    envs = calkit.markdown.get_environments(
        doc,
        existing_env_names=list(ck_info.get("environments", {}) or {}),
        default_env=environment,
    )
    # Record each detected environment on the block that needs it, since
    # the annotation is the only place a per-stage environment can live;
    # a stage it can't be recorded on would silently run in _system.
    for stage_name, env_name in envs.assignments.items():
        text, changed = calkit.markdown.set_stage_attrs(
            text, stage_name, {"environment": env_name}
        )
        if not changed:
            raise_error(
                f"Could not record environment '{env_name}' on stage "
                f"'{stage_name}' in {markdown_path}"
            )
    # A project has to exist before the stages can run, and running xr on
    # a Markdown file is a clear enough statement of intent to create one.
    # Nothing is committed: a failed bootstrap has to be able to put
    # everything back, and files can be restored where commits can't.
    dvc_existed = os.path.isdir(".dvc")
    md_derived_existed = os.path.isdir(".calkit/markdown")
    # Keep the files themselves rather than reparsed copies, so a failed
    # bootstrap (or --no-record) restores what was there byte for byte---
    # including the case where there was no file at all. Taken before
    # initializing, which is what creates calkit.yaml. Running compiles
    # the pipeline and builds environments too, so everything that writes
    # is covered, not just the files written here.
    snapshot = _snapshot(
        [
            "calkit.yaml",
            "dvc.yaml",
            "dvc.lock",
            ".gitignore",
            ".dvcignore",
            STAGE_RUNS_FPATH,
        ]
    )
    if not dry_run and not project_is_initialized():
        typer.echo(f"Initializing project in {os.getcwd()}")
        init(no_commit=True)
        ck_info = calkit.load_calkit_info()
    stages = ck_info.setdefault("pipeline", {}).setdefault("stages", {})
    stage: dict[str, Any] = {"kind": "markdown", "target_path": markdown_path}
    if environment is not None:
        stage["environment"] = environment
    detected_envs = envs.detected_public
    if dry_run:
        out = io.StringIO()
        calkit.ryaml.dump({markdown_path: stage}, out)
        typer.echo(out.getvalue().rstrip())
        for env_name, env in detected_envs.items():
            env_out = io.StringIO()
            calkit.ryaml.dump({env_name: env}, env_out)
            typer.echo(env_out.getvalue().rstrip())
        return
    env_dirs = sorted(
        {os.path.dirname(env["path"]) for env in detected_envs.values()}
    )
    new_env_dirs = [d for d in env_dirs if d and not os.path.isdir(d)]
    # Environments declared in the file are built during the run, so what
    # was under .calkit/envs beforehand is recorded now, to tell a failed
    # run's environments from ones that were already there
    envs_root = os.path.join(".calkit", "envs")
    pre_env_dirs = (
        set(os.listdir(envs_root)) if os.path.isdir(envs_root) else None
    )
    if envs.detected:
        calkit.markdown.write_env_specs(envs.detected)
        ck_info.setdefault("environments", {}).update(detected_envs)
    if text != original_text:
        with open(markdown_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    stages[markdown_path] = stage
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)

    def _restore_record() -> None:
        """Put back the files that record the pipeline.

        Derived files under .calkit are left alone: they are what there
        is to inspect, and nothing tracks them.
        """
        for path, content in snapshot.items():
            if content is None:
                if os.path.isfile(path):
                    os.remove(path)
            else:
                with open(path, "wb") as fb:
                    fb.write(content)
        if not dvc_existed:
            shutil.rmtree(".dvc", ignore_errors=True)
        # The bootstrap stages what it creates, so the index has to be put
        # back too, or a deleted calkit.yaml lingers as a staged addition
        _unstage_record([*snapshot, ".dvc"])

    def _cleanup_derived() -> None:
        """Remove the derived files this run created.

        The run log under .calkit/local stays---it is self-ignored and is
        where the detail of what happened lives.
        """
        for env_dir in new_env_dirs:
            shutil.rmtree(env_dir, ignore_errors=True)
        if pre_env_dirs is None:
            shutil.rmtree(envs_root, ignore_errors=True)
        elif os.path.isdir(envs_root):
            for env_dir_name in set(os.listdir(envs_root)) - pre_env_dirs:
                shutil.rmtree(
                    os.path.join(envs_root, env_dir_name), ignore_errors=True
                )
        if not md_derived_existed:
            shutil.rmtree(".calkit/markdown", ignore_errors=True)

    try:
        run(targets=[markdown_path], force=force, verbose=verbose)
    except BaseException as e:
        # Put back everything this touched---on an interrupt too, which
        # would otherwise leave a compiled dvc.yaml pointing at a stage
        # no calkit.yaml declares---so a failed bootstrap leaves no
        # half-recorded pipeline behind. What a failed run created is
        # removed as well; the log under .calkit/local has the details.
        _restore_record()
        if text != original_text:
            with open(markdown_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(original_text)
        _cleanup_derived()
        if not isinstance(e, Exception):
            raise
        raise_error(f"Failed to execute stages in {markdown_path}: {e}")
    if no_record:
        # The stages ran; what remains is their evidence---the annotated
        # file, injected output, and whatever the stages wrote---not the
        # machinery: the record files are restored and the derived
        # scripts and environments removed, leaving only the run log
        # under .calkit/local.
        _restore_record()
        _cleanup_derived()
        typer.echo(
            "Executed without recording: calkit.yaml, dvc.yaml and .dvc "
            "were restored and derived files removed; the run log is "
            "under .calkit/local/logs/"
        )


@app.command(name="xr")
def execute_and_record(
    cmd: Annotated[
        list[str],
        typer.Argument(
            help="Command to execute and record. "
            "If the first argument is a script, notebook or LaTeX file, "
            "it will be treated as a stage with that file as "
            "the target. Any command, including arguments, is supported."
        ),
    ],
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment",
            "-e",
            help="Name of or path the spec file for the environment to use.",
        ),
    ] = None,
    inputs: Annotated[
        list[str],
        typer.Option(
            "--input",
            "-i",
            help="Input paths to record.",
        ),
    ] = [],
    outputs: Annotated[
        list[str],
        typer.Option(
            "--output",
            "-o",
            help="Output paths to record.",
        ),
    ] = [],
    no_detect_io: Annotated[
        bool,
        typer.Option(
            "--no-detect-io",
            help=(
                "Don't attempt to detect inputs and outputs from the command, "
                "script, or notebook."
            ),
        ),
    ] = False,
    stage_name: Annotated[
        str | None,
        typer.Option(
            "--stage",
            help=(
                "Name of the DVC stage to create for this command. If not "
                "provided, a name will be generated automatically."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-d",
            help=(
                "Print the environment and stage that would be created "
                "without modifying calkit.yaml or executing the command."
            ),
        ),
    ] = False,
    no_record: Annotated[
        bool,
        typer.Option(
            "--no-record",
            help=(
                "Execute without recording: run as usual, then restore "
                "calkit.yaml, dvc.yaml and .dvc and remove derived "
                "files, keeping only what the run produced (annotations, "
                "injected output, stage outputs) and the run log. Useful "
                "for checking that a Markdown file is runnable in a "
                "project that isn't a Calkit project."
            ),
        ),
    ] = False,
    fmt_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Print xr results as JSON.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force running stage even if it's up-to-date.",
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Execute a command and if successful, record in the pipeline."""
    import contextlib
    import io

    from calkit.pipeline.detect import detect_stage, normalize_command

    # First, read the pipeline before running so we can revert if the stage
    # fails
    ck_info = calkit.load_calkit_info()
    ck_info_orig = deepcopy(ck_info)
    # What records the pipeline, taken before anything below writes---the
    # detected environment included---so --no-record can put it all back
    # after running (environment spec files and outputs stay behind for
    # inspection)
    record_snapshot: dict[str, bytes | None] = {}
    if no_record:
        for record_path in [
            "calkit.yaml",
            "dvc.yaml",
            "dvc.lock",
            STAGE_RUNS_FPATH,
        ]:
            if os.path.isfile(record_path):
                with open(record_path, "rb") as fb:
                    record_snapshot[record_path] = fb.read()
            else:
                record_snapshot[record_path] = None
    try:
        cmd, environment = normalize_command(cmd, environment)
    except ValueError as e:
        raise_error(str(e))
    first_arg = cmd[0]
    # A Markdown file is a stage of its own kind
    if first_arg.endswith(".md"):
        _xr_markdown(
            markdown_path=first_arg,
            ck_info=ck_info,
            environment=environment,
            dry_run=dry_run,
            force=force,
            verbose=verbose,
            no_record=no_record,
        )
        return
    try:
        detection = detect_stage(
            cmd,
            ck_info,
            environment=environment,
            stage_name=stage_name,
            inputs=inputs,
            outputs=outputs,
            detect_paths=not no_detect_io,
        )
    except ValueError as e:
        raise_error(str(e))
    for note in detection.notes:
        typer.echo(note)
    for problem in detection.problems:
        typer.echo(f"Warning: {problem}", err=True)
    env_result = detection.environment
    stage_name = detection.stage.name
    stage = detection.stage.stage
    external_inputs = detection.external_inputs
    language = detection.language
    # If we created an environment from dependencies, write the spec file
    if env_result.created_from_dependencies and not dry_run:
        typer.echo(
            "No existing environment detected; "
            "Attempting to create one based on detected dependencies"
        )
        if env_result.dependencies:
            typer.echo(
                f"Detected {language or 'code'} dependencies: "
                f"{', '.join(env_result.dependencies)}"
            )
        if env_result.spec_path and env_result.spec_content is not None:
            # Create the spec file
            spec_dir = os.path.dirname(env_result.spec_path)
            if spec_dir:
                os.makedirs(spec_dir, exist_ok=True)
            with open(env_result.spec_path, "w") as f:
                f.write(env_result.spec_content)
            typer.echo(f"Created environment spec: {env_result.spec_path}")
    # Add environment to calkit.yaml if it doesn't exist
    if not env_result.exists and not dry_run:
        envs = ck_info.get("environments", {})
        envs[env_result.name] = env_result.env
        ck_info["environments"] = envs
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        ck_info = calkit.load_calkit_info()
    env_name = env_result.name
    pipeline = ck_info.get("pipeline", {})
    stages = pipeline.get("stages", {})

    def _xr_json_result(
        mode: str,
        execution_status: str | None = None,
        error: str | None = None,
        run_stdout: str | None = None,
        run_stderr: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"mode": mode, **detection.model_dump()}
        if execution_status is not None:
            result["execution"] = {
                "status": execution_status,
                "error": error,
                "stdout": run_stdout,
                "stderr": run_stderr,
            }
        return result

    # Data read from outside the project is only on this machine
    if not fmt_json:
        for path in external_inputs:
            warn(
                f"This reads {path}, which is outside the project, so it "
                "will fail on other machines; move the data into the project "
                "and read it from there"
            )
    # If dry-run, print environment and stage then return
    if dry_run:
        if fmt_json:
            typer.echo(json.dumps(_xr_json_result(mode="dry-run"), indent=2))
            return
        # Print environment info
        if env_result.created_from_dependencies:
            typer.echo("Environment (would be created):")
            if env_result.spec_path and env_result.spec_content is not None:
                typer.echo(f"  Spec file: {env_result.spec_path}")
                typer.echo("  Content:")
                for line in env_result.spec_content.split("\n"):
                    typer.echo(f"    {line}")
        elif not env_result.exists:
            typer.echo("Environment (would be added to calkit.yaml):")
            yaml_output = io.StringIO()
            calkit.ryaml.dump({env_result.name: env_result.env}, yaml_output)
            for line in yaml_output.getvalue().rstrip().split("\n"):
                typer.echo(f"  {line}")
        else:
            typer.echo(f"Environment: {env_name} (already exists)")
        # Print stage
        typer.echo("\nStage (would be added to pipeline):")
        yaml_output = io.StringIO()
        calkit.ryaml.dump({stage_name: stage}, yaml_output)
        for line in yaml_output.getvalue().rstrip().split("\n"):
            typer.echo(f"  {line}")
        return
    stages[stage_name] = stage
    pipeline["stages"] = stages
    ck_info["pipeline"] = pipeline
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    run_stdout = io.StringIO()
    run_stderr = io.StringIO()
    try:
        if not fmt_json:
            # Format stage as YAML for display
            yaml_output = io.StringIO()
            calkit.ryaml.dump({stage_name: stage}, yaml_output)
            # Indent YAML by 2 spaces
            indented_yaml = "\n".join(
                "  " + line if line.strip() else line
                for line in yaml_output.getvalue().rstrip().split("\n")
            )
            typer.echo(
                (
                    "Executing without recording:"
                    if no_record
                    else "Adding stage to pipeline and attempting to execute:"
                )
                + f"\n{indented_yaml}"
            )
            run(targets=[stage_name], force=force, verbose=verbose)
        else:
            with contextlib.redirect_stdout(run_stdout):
                with contextlib.redirect_stderr(run_stderr):
                    run(
                        targets=[stage_name],
                        force=force,
                        verbose=verbose,
                        quiet=True,
                    )
            stdout_value = run_stdout.getvalue().rstrip() or None
            stderr_value = run_stderr.getvalue().rstrip() or None
            typer.echo(
                json.dumps(
                    _xr_json_result(
                        mode="run",
                        execution_status="completed",
                        run_stdout=stdout_value,
                        run_stderr=stderr_value,
                    ),
                    indent=2,
                )
            )
        if no_record:
            for record_path, content in record_snapshot.items():
                if content is None:
                    if os.path.isfile(record_path):
                        os.remove(record_path)
                else:
                    with open(record_path, "wb") as fw:
                        fw.write(content)
            # The run stages what it writes when autostaging
            _unstage_record(list(record_snapshot))
            typer.echo(
                "Executed without recording; the stage was not added to "
                "the pipeline"
            )
    except Exception as e:
        # If the stage failed, write the old ck_info back to calkit.yaml to
        # remove the stage that we added
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info_orig, f)
        if fmt_json:
            stdout_value = run_stdout.getvalue().rstrip() or None
            stderr_value = run_stderr.getvalue().rstrip() or None
            typer.echo(
                json.dumps(
                    _xr_json_result(
                        mode="run",
                        execution_status="failed",
                        error=f"Failed to execute stage: {e}",
                        run_stdout=stdout_value,
                        run_stderr=stderr_value,
                    ),
                    indent=2,
                )
            )
            raise typer.Exit(code=1)
        raise_error(f"Failed to execute stage: {e}")
