"""CLI for working with Overleaf."""

from __future__ import annotations

import filecmp
import json
import os
import posixpath
import subprocess
import sys
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import AliasGroup, raise_error, warn
from calkit.cli.sync import sync_app

if TYPE_CHECKING:
    import git

overleaf_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)

# How many times the guided commands retry a failed pull before giving up
# when running unattended, where there's nobody to stop an endless retry
_MAX_PULL_ATTEMPTS = 3


def _extract_title_from_tex(tex_file_path: str) -> str | None:
    """Extract the title from a LaTeX file."""
    from TexSoup import TexSoup

    try:
        with open(tex_file_path) as f:
            overleaf_target_text = f.read()
        texsoup = TexSoup(overleaf_target_text)
        return str(texsoup.title.string) if texsoup.title else None
    except Exception:
        return None


def _get_overleaf_token(rejected: bool = False) -> str:
    """Get the user's Overleaf token from config, prompting for one if it
    isn't set or Overleaf ``rejected`` it.
    """
    calkit_config = calkit.config.read()
    overleaf_token = None if rejected else calkit_config.overleaf_token
    if not overleaf_token:
        if rejected:
            warn(
                "Overleaf rejected your token; "
                "it may have expired or been revoked",
                prefix="",
            )
        else:
            warn("Overleaf token not set in config", prefix="")
        typer.echo(
            "A new one can be generated at:\n\n"
            "    https://www.overleaf.com/user/settings\n\n"
            "under the 'Git Integration' section.\n"
            "Without Overleaf Premium, run 'calkit overleaf login' instead.\n"
        )
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise_error(
                "Set one with 'calkit config set overleaf_token' and try again"
            )
        overleaf_token = typer.prompt(
            "Enter Overleaf Git authentication token", hide_input=True
        )
        typer.echo("Storing Overleaf token in Calkit config")
        calkit_config.overleaf_token = overleaf_token
        calkit_config.write()
    if not overleaf_token:
        raise_error(
            "Overleaf token not set in config; "
            "Please set it using 'calkit config set overleaf_token'"
        )
    return overleaf_token


def _get_overleaf_auth() -> str | calkit.overleaf.WebClient:
    """Get a Git token, or, if only a session is available, a web client
    for syncing without Overleaf Premium.

    Credentials in config come first, then a token saved to the hub, before
    prompting for a token.
    """
    calkit_config = calkit.config.read()
    if calkit_config.overleaf_token:
        return calkit_config.overleaf_token
    if calkit_config.overleaf_session:
        return calkit.overleaf.WebClient(calkit_config.overleaf_session)
    if calkit_config.token is not None:
        try:
            typer.echo("Getting Overleaf token from the hub")
            token = calkit.hub.get("/user/overleaf-token")["access_token"]
            calkit_config.overleaf_token = token
            calkit_config.write()
            return str(token)
        except Exception:
            typer.echo("No Overleaf token on the hub")
    return _get_overleaf_token()


def _get_pulled_overleaf_repo(
    project_id: str, auth: str | calkit.overleaf.WebClient
) -> tuple[git.Repo, str | calkit.overleaf.WebClient]:
    """Clone or pull an Overleaf project, asking for new credentials
    whenever Overleaf rejects the current ones.

    Returns the repo and the credentials that worked, so later projects use
    them too.
    """

    def get_new_session() -> str:
        """Prompt for a new Overleaf session and store it."""
        warn("Overleaf rejected your session", prefix="")
        typer.echo(calkit.overleaf.SESSION_HELP + "\n")
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise_error(
                "Set one with 'calkit overleaf login --session' and try again"
            )
        session = typer.prompt(
            "Enter Overleaf session cookie", hide_input=True
        )
        calkit_config = calkit.config.read()
        calkit_config.overleaf_session = calkit.config.KeyringOptionalSecret(
            session
        )
        calkit_config.write()
        return str(session)

    while True:
        try:
            if isinstance(auth, calkit.overleaf.WebClient):
                repo = calkit.overleaf.get_mirror(project_id)
                calkit.overleaf.pull_mirror(repo, auth, project_id)
            else:
                repo = calkit.overleaf.get_repo(project_id, auth)
                calkit.overleaf.pull(repo)
            return repo, auth
        except calkit.overleaf.AuthError as e:
            if isinstance(auth, calkit.overleaf.WebClient):
                warn(str(e), prefix="")
                auth = calkit.overleaf.WebClient(get_new_session())
            else:
                # A token stops working when Premium ends, but a browser
                # session still does
                session = calkit.config.read().overleaf_session
                if session:
                    warn(
                        "Overleaf rejected your Git token; "
                        "using your browser session instead",
                        prefix="",
                    )
                    auth = calkit.overleaf.WebClient(str(session))
                else:
                    auth = _get_overleaf_token(rejected=True)
        except Exception as e:
            raise_error(str(e))


@overleaf_app.command(name="login")
def login(
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            help="Value of the 'overleaf_session2' cookie from your browser.",
        ),
    ] = None,
) -> None:
    """Sign in with a browser session to sync without Overleaf Premium."""
    if session is None:
        typer.echo(calkit.overleaf.SESSION_HELP + "\n")
        session = str(
            typer.prompt("Enter Overleaf session cookie", hide_input=True)
        )
    try:
        calkit.overleaf.WebClient(session).csrf_token
    except Exception as e:
        raise_error(str(e))
    calkit_config = calkit.config.read()
    calkit_config.overleaf_session = calkit.config.KeyringOptionalSecret(
        session
    )
    calkit_config.write()
    typer.echo("Stored Overleaf session in Calkit config")
    if calkit_config.overleaf_token:
        warn(
            "An Overleaf Git token is also set and will be used instead; "
            "remove it with 'calkit config unset overleaf_token'"
        )


@overleaf_app.command(name="import")
def import_publication(
    src_url: Annotated[
        str,
        typer.Argument(
            help=(
                "Overleaf project URL, e.g., "
                "https://www.overleaf.com/project/6800005973cb2e35."
            )
        ),
    ],
    dest_dir: Annotated[
        str,
        typer.Argument(
            help="Directory at which to save in the project, e.g., 'paper'."
        ),
    ],
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            "-t",
            help="Title of the publication.",
        ),
    ] = None,
    target_path: Annotated[
        str | None,
        typer.Option(
            "--target",
            "-T",
            help="Target TeX file path inside Overleaf project.",
        ),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            "-d",
            help="Description of the publication.",
        ),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            help="What of the publication this is, e.g., 'journal-article'.",
        ),
    ] = None,
    push_paths: Annotated[
        list[str],
        typer.Option(
            "--push-path",
            "-p",
            help=(
                "Paths to push to the Overleaf project, e.g., 'figures'. "
                "Note that these are relative to the publication working "
                "directory."
            ),
        ),
    ] = [],
    no_commit: Annotated[
        bool,
        typer.Option("--no-commit", help="Do not commit changes to repo."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Force adding the publication even if it already exists.",
        ),
    ] = False,
    push_only: Annotated[
        bool,
        typer.Option(
            "--push-only",
            "-P",
            help=(
                "Push local files to Overleaf without pulling. "
                "Useful when initializing a new Overleaf project from local "
                "files."
            ),
        ),
    ] = False,
):
    """Import a publication from an Overleaf project."""
    from calkit.cli.main import ignore as git_ignore
    from calkit.cli.new import new_latex_stage

    # First check that the user can access Overleaf
    overleaf_auth = _get_overleaf_auth()
    if (
        not src_url.startswith("https://www.overleaf.com/project/")
        and calkit.config.get_env() != "test"
    ):
        raise_error(
            "Invalid URL; must start with 'https://www.overleaf.com/project/'"
        )
    overleaf_project_id = calkit.overleaf.project_id_from_url(src_url)
    if not overleaf_project_id:
        raise_error("Invalid Overleaf project ID")
    # Check target path
    if target_path is not None and not target_path.endswith(".tex"):
        raise_error("Target path should have a .tex extension")
    # Make sure destination directory exists, and isn't a file
    if os.path.isfile(dest_dir):
        raise_error("Destination must be a directory, not a file")
    os.makedirs(dest_dir, exist_ok=True)
    ck_info = calkit.load_calkit_info()
    pubs = ck_info.get("publications", [])
    # TODO: Don't allow the same Overleaf project ID in multiple publications
    repo = calkit.git.get_repo()
    # Clone the Overleaf project into .calkit/overleaf if it doesn't exist
    # otherwise pull
    overleaf_dir = os.path.join(".calkit", "overleaf")
    os.makedirs(overleaf_dir, exist_ok=True)
    git_ignore(overleaf_dir, no_commit=no_commit)
    overleaf_project_dir = calkit.overleaf.get_project_dir(overleaf_project_id)
    if os.path.isdir(overleaf_project_dir):
        warn("This Overleaf project has already been cloned; removing")
        calkit.overleaf.rmtree(overleaf_project_dir)
    # Clone the Overleaf project
    typer.echo("Cloning Overleaf project")
    # Closed so Git's helper processes don't keep the folder open on Windows
    _get_pulled_overleaf_repo(overleaf_project_id, overleaf_auth)[0].close()
    # Detect target path if not specified
    if target_path is None:
        ol_contents = os.listdir(
            dest_dir if push_only else overleaf_project_dir
        )
        for cand in ["main.tex", "report.tex", "paper.tex"]:
            if cand in ol_contents:
                target_path = cand
                break
    if target_path is None:
        # Fall back to lone .tex file if there is one
        tex_files = [p for p in ol_contents if p.endswith(".tex")]
        if len(tex_files) == 1:
            target_path = tex_files[0]
    if target_path is None:
        raise_error(
            "Target TeX file path cannot be detected; "
            "please specify with --target"
        )
        return
    # Try to extract title from the target LaTeX file if not provided
    if not title:
        target_tex_path = os.path.join(
            dest_dir if push_only else overleaf_project_dir, target_path
        )
        extracted_title = _extract_title_from_tex(target_tex_path)
        if extracted_title:
            typer.echo(f"Detected title: {extracted_title}")
            title = extracted_title
    if not title:
        raise_error(
            "Title could not be detected from the LaTeX file; "
            "please specify with --title"
        )
    # Determine the PDF output path
    pdf_path = target_path.removesuffix(".tex") + ".pdf"  # type: ignore
    typer.echo(f"Using PDF path: {pdf_path}")
    tex_path = pdf_path.removesuffix(".pdf") + ".tex"
    target_tex_path = Path(dest_dir, tex_path).as_posix()
    pub_path = Path(dest_dir, pdf_path).as_posix()
    pub_paths = [pub.get("path") for pub in pubs]
    if not overwrite and pub_path in pub_paths:
        raise_error(
            f"A publication already exists in this project at {pub_path}"
        )
    elif overwrite and pub_path in pub_paths:
        # Note: This publication will go to the end of the list
        pubs = [p for p in pubs if p.get("path") != pub_path]
    # Check that we have a LaTeX environment
    typer.echo("Checking that this project has a LaTeX environment")
    envs = ck_info.get("environments", {})
    tex_env_name = None
    for name, env in envs.items():
        image = env.get("image", "")
        if env.get("kind") == "docker" and (
            "texlive" in image or "calkit/latex" in image
        ):
            tex_env_name = name
            break
    if tex_env_name is None:
        from calkit.latex import DEFAULT_LATEX_ENVIRONMENT

        typer.echo("Creating TeX Live Docker environment")
        tex_env_name = "tex"
        n = 1
        while tex_env_name in envs:
            tex_env_name = f"tex-{n}"
            n += 1
        envs[tex_env_name] = dict(DEFAULT_LATEX_ENVIRONMENT)
        ck_info["environments"] = envs
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
    # Check that we have a build stage
    typer.echo("Checking for a build stage in the pipeline")
    pipeline = ck_info.get("pipeline", {})
    stages = pipeline.get("stages", {})
    stage_name = None
    for stage_name_i, stage in stages.items():
        if (
            stage.get("kind") == "latex"
            and stage.get("target_path") == target_tex_path
        ):
            stage_name = stage_name_i
            typer.echo(f"Found build stage '{stage_name}' in pipeline")
            break
    if stage_name is None:
        # Create a new stage
        stage_name = calkit.to_kebab_case("build-" + dest_dir)
        n = 1
        while stage_name in stages:
            stage_name = f"{stage_name}-{n}"
            n += 1
        typer.echo(f"Creating build stage '{stage_name}'")
        new_latex_stage(
            name=stage_name,
            environment=tex_env_name,
            target_path=target_tex_path,
            inputs=[os.path.join(dest_dir, p) for p in push_paths],
            no_check=True,
            no_commit=True,
        )
        repo.git.add("calkit.yaml")
    # Add to publications in calkit.yaml
    typer.echo("Adding publication to calkit.yaml")
    ck_info = calkit.load_calkit_info()
    new_pub = dict(
        path=pub_path,
        title=title,
        description=description,
        kind=kind,
        stage=stage_name,
    )
    pubs.append(new_pub)
    ck_info["publications"] = pubs
    ol_sync = ck_info.get("overleaf_sync", {})
    if dest_dir in ol_sync:
        raise_error(f"'{dest_dir}' is already synced with Overleaf")
    ol_sync[dest_dir] = dict(url=src_url)
    if push_paths:
        ol_sync[dest_dir]["push_paths"] = push_paths
    ck_info["overleaf_sync"] = ol_sync
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if not no_commit and repo.git.diff(["--staged", "--", "calkit.yaml"]):
        # Commit any necessary changes
        typer.echo("Committing changes")
        repo.git.commit(
            [
                "calkit.yaml",
                "-m",
                f"Import Overleaf project ID {overleaf_project_id}",
            ]
        )
    # Sync the project. The build stage was just created and so has never
    # run, and linking a document isn't the moment to insist on a current
    # pipeline or branch.
    sync(
        paths=[dest_dir],
        no_commit=no_commit,
        push_only=push_only,
        allow_stale=True,
        any_branch=True,
    )


def _get_document_stages(folders: list[str]) -> dict[str, str]:
    """LaTeX stages that build a document in these folders, keyed to the
    folder.
    """
    stages = (calkit.load_calkit_info().get("pipeline") or {}).get(
        "stages"
    ) or {}
    return {
        name: folder
        for name, stage in stages.items()
        if isinstance(stage, dict)
        and stage.get("kind") == "latex"
        and stage.get("target_path")
        for folder in folders
        if Path(
            posixpath.normpath(
                posixpath.join(
                    stage.get("wdir") or ".", str(stage["target_path"])
                )
            )
        ).is_relative_to(folder)
    }


def check_sync_readiness(
    check_branch: bool = True,
    check_pipeline: bool = True,
    synced_folders: list[str] | None = None,
) -> dict:
    """Look for reasons this is a risky moment to sync with Overleaf.

    Overleaf has no branches, so whatever is synced there is what
    collaborators see and write against. Two things make that misleading:
    a branch that doesn't contain everything already on the default branch,
    which can send someone else's work backwards, and an out-of-date
    pipeline, which can send figures or results that don't match the code
    that supposedly made them.

    With ``synced_folders``, only out-of-date stages that feed what's sent
    count: those the folders' document builds depend on, and those that
    write into the folders. The builds themselves don't, since their PDFs
    aren't sent, and are returned as ``stale_documents`` to rebuild after.

    Returns a dict with a ``branch`` message, a ``pipeline`` message, and
    the ``stale_stages`` behind the latter. Each message is None when that
    check passes or can't be run.
    """
    import calkit.dvc

    res: dict = {
        "branch": None,
        "pipeline": None,
        "stale_stages": [],
        "stale_documents": [],
    }
    if check_branch:
        try:
            res["branch"] = calkit.git.check_branch_is_current(
                calkit.git.get_repo()
            )
        except Exception as e:
            warn(f"Could not check branch is current: {e}")
    if check_pipeline:
        # Environments are left alone here: what matters is whether the
        # outputs match the code that made them, and checking would build or
        # pull environments as a side effect of a sync, which is a surprising
        # thing for a sync to do. Running the pipeline checks them anyway.
        status = calkit.pipeline.get_status(
            check_environments=False,
            clean_notebooks=True,
            compile_to_dvc=True,
        )
        if status.errors:
            res["pipeline"] = "Pipeline checks failed: " + "; ".join(
                status.errors
            )
        elif status.failed_environment_checks:
            res["pipeline"] = (
                "Pipeline environment checks failed for: "
                + ", ".join(status.failed_environment_checks)
            )
        elif status.is_stale:
            stale = status.stale_stage_names
            if synced_folders is not None:
                docs = _get_document_stages(synced_folders)
                try:
                    feeding: set[str] = set()
                    for name in docs:
                        feeding |= calkit.pipeline.get_upstream_stages(name)
                    dvc_stages = calkit.dvc.read_pipeline().get("stages", {})
                    for name, stage in dvc_stages.items():
                        stage_wdir = stage.get("wdir") or "."
                        outs = calkit.dvc.out_paths_from_stage(stage)
                        if any(
                            Path(
                                posixpath.normpath(
                                    posixpath.join(stage_wdir, out)
                                )
                            ).is_relative_to(folder)
                            for out in outs
                            for folder in synced_folders
                        ):
                            feeding.add(name)
                except Exception as e:
                    # Then every out-of-date stage counts
                    warn(f"Could not check which stages feed Overleaf: {e}")
                else:
                    res["stale_documents"] = [s for s in stale if s in docs]
                    stale = [
                        s for s in stale if s in feeding and s not in docs
                    ]
            res["stale_stages"] = stale
            if stale:
                res["pipeline"] = (
                    "Pipeline is not up-to-date; out-of-date stages: "
                    + ", ".join(stale)
                )
    return res


@sync_app.command(name="overleaf")
@overleaf_app.command(name="sync")
def sync(
    paths: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Paths to sync with Overleaf, e.g., 'paper/paper.pdf'. "
                "If not provided, all Overleaf publications will be synced."
            ),
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit",
            help=(
                "Do not create a commit in the project repo for this sync. "
                "Changes pulled from Overleaf are still applied, but are "
                "left staged so you can review or commit them yourself. "
                "Changes are always committed and pushed to Overleaf "
                "regardless."
            ),
        ),
    ] = False,
    auto_commit: Annotated[
        bool,
        typer.Option(
            "--auto-commit",
            "-a",
            help="Deprecated; local edits are now committed automatically.",
            hidden=True,
        ),
    ] = False,
    no_push: Annotated[
        bool,
        typer.Option(
            "--no-push",
            help=(
                "Do not push the changes to the main project remote. "
                "Changes will always be pushed to Overleaf."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Enable verbose output.",
        ),
    ] = False,
    resolve: Annotated[
        bool,
        typer.Option(
            "--resolve",
            "-r",
            help="Mark merge conflicts as resolved before committing.",
        ),
    ] = False,
    push_only: Annotated[
        bool,
        typer.Option(
            "--push-only",
            "-P",
            help=(
                "Only push local files to Overleaf without pulling from "
                "Overleaf. "
                "Useful when initializing a new Overleaf project from local "
                "files."
            ),
        ),
    ] = False,
    allow_stale: Annotated[
        bool,
        typer.Option(
            "--allow-stale",
            help=(
                "Sync even if the pipeline is out-of-date, which can send "
                "stale figures or results to Overleaf."
            ),
        ),
    ] = False,
    any_branch: Annotated[
        bool,
        typer.Option(
            "--any-branch",
            help=(
                "Sync even if the current branch is missing commits from the "
                "default branch."
            ),
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Overwrite changes made on Overleaf to push-only paths, "
                "which the project is meant to be the source of truth for."
            ),
        ),
    ] = False,
    no_build: Annotated[
        bool,
        typer.Option(
            "--no-build",
            help=(
                "Only sync source files, without rebuilding documents "
                "changed on Overleaf."
            ),
        ),
    ] = False,
    upstream: Annotated[
        bool,
        typer.Option(
            "--upstream",
            help="When rebuilding, also run stages the build depends on.",
        ),
    ] = False,
):
    """Sync folders with Overleaf.

    Local edits are committed first, and documents changed on either side
    are rebuilt and saved with the sync.
    """
    import calkit.dvc
    from calkit.cli.main.core import push as calkit_push
    from calkit.cli.main.core import run as calkit_run

    def get_dirty_files() -> dict[str, tuple[str | None, bool]]:
        """Changed and untracked files, with a hash of their content and
        whether they're untracked.
        """
        untracked: dict[str, bool] = {}
        entries = iter(
            repo.git.status(
                "--porcelain", "-z", "--untracked-files=all"
            ).split("\0")
        )
        for entry in entries:
            if not entry:
                continue
            # A rename or copy is followed by the path it came from
            if entry[0] in "RC":
                next(entries, None)
            untracked[entry[3:]] = entry.startswith("??")
        existing = [
            path
            for path in untracked
            if os.path.isfile(os.path.join(repo.working_dir, path))
        ]
        hashes = subprocess.run(
            ["git", "hash-object", "--stdin-paths"],
            input="\n".join(existing),
            cwd=repo.working_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        content = dict(zip(existing, hashes))
        return {path: (content.get(path), u) for path, u in untracked.items()}

    repo = calkit.git.get_repo()
    # Uncommitted edits to calkit.yaml aren't the sync's to touch or commit,
    # so fixing the legacy schema waits until there are none
    calkit_yaml_dirty = bool(repo.git.diff("HEAD", "--", "calkit.yaml"))
    overleaf_info = calkit.overleaf.get_sync_info(
        fix_legacy=not calkit_yaml_dirty, print_info=typer.echo
    )
    if not overleaf_info:
        raise_error("No Overleaf sync info found")
    overleaf_sync_dirs = list(overleaf_info.keys())
    if paths is not None:
        paths = [
            (os.path.dirname(p) if os.path.isfile(p) else p)
            .strip()
            .rstrip("/\\")
            for p in paths
        ]
        for path in paths:
            if path not in overleaf_sync_dirs:
                raise_error(f"Path '{path}' is not synced with Overleaf")
    synced_folders = [
        f for f in overleaf_sync_dirs if paths is None or f in paths
    ]
    # Check this is a sane state to sync from before touching either side.
    # Resolving a conflict is the middle of a sync that already passed these,
    # and the pipeline can't be current until it finishes.
    readiness = check_sync_readiness(
        check_branch=not any_branch and not resolve,
        check_pipeline=not allow_stale and not resolve,
        synced_folders=synced_folders,
    )
    if readiness["branch"]:
        raise_error(
            readiness["branch"]
            + ".\nOverleaf has no branches, so syncing from here can send "
            "collaborators a version that's missing work already on the "
            "default branch.\nMerge or rebase first, or use --any-branch to "
            "sync anyway."
        )
    if readiness["pipeline"]:
        raise_error(
            readiness["pipeline"]
            + ".\nSyncing now could send stale figures or results to "
            "Overleaf.\nRun 'calkit run' first, or use --allow-stale to sync "
            "anyway."
        )
    overleaf_auth = _get_overleaf_auth()
    conflict_fpath = calkit.overleaf.get_conflict_fpath()
    in_am_session = "in the middle of an am session" in repo.git.status()
    # Check if we're in the middle of resolving a merge conflict
    if in_am_session and not resolve:
        raise_error(
            "You are in the middle of resolving a merge conflict; "
            "use 'calkit overleaf sync --resolve' after editing file(s)"
        )
    elif resolve:
        if not os.path.isfile(conflict_fpath):
            raise_error("No merge conflict to resolve")
        # Figure out which wdir has the conflict in it
        with open(conflict_fpath) as f:
            resolving_info = json.load(f)
    # Keyed by synced folder, so a sync of multiple folders can be summarized
    # after the loop even if some are skipped
    results: dict[str, dict] = {}
    edited_folders: set[str] = set()
    first = True
    for synced_folder, sync_data in overleaf_info.items():
        if not sync_data:
            continue
        if paths is not None and synced_folder not in paths:
            continue
        overleaf_project_id = sync_data.get("project_id")
        if not overleaf_project_id:
            raise_error(
                "No Overleaf project ID defined for this folder; "
                "please set 'url' in the Overleaf config"
            )
        # Separate each folder's output from the one before
        if not first:
            typer.echo()
        first = False
        folder = typer.style(synced_folder, fg="blue")
        typer.echo(
            f"Syncing {folder} with Overleaf project ID {overleaf_project_id}"
        )
        wdir = synced_folder
        if resolve and wdir == resolving_info["wdir"]:
            repo.git.add(wdir)
            if repo.git.diff(["--staged", wdir]):
                repo.git.commit(
                    [wdir, "-m", f"Resolve Overleaf merge conflict in {wdir}"]
                )
            if in_am_session:
                with calkit.overleaf.staged_changes_set_aside(repo):
                    repo.git.am("--skip")
        elif resolve:
            continue
        # Local edits are saved first so they're what's synced and rebuilt
        # from. Untracked files aren't sent to Overleaf, so they're left out.
        if repo.git.diff(wdir) or repo.index.diff("HEAD", wdir):
            if no_commit:
                raise_error(
                    f"Uncommitted changes found in {wdir}. "
                    "Commit or stash them before syncing with --no-commit."
                )
            typer.echo(f"Committing local edits in {wdir}")
            repo.git.add("-u", "--", wdir)
            repo.git.commit(
                [wdir, "-m", f"Update {wdir} before Overleaf sync"]
            )
            edited_folders.add(wdir)
        # Keep other processes from using the clone until we're done
        with (
            calkit.overleaf.lock(overleaf_project_id, typer.echo),
            ExitStack() as cleanup,
        ):
            typer.echo("Pulling the latest version from Overleaf")
            overleaf_repo, overleaf_auth = _get_pulled_overleaf_repo(
                overleaf_project_id, overleaf_auth
            )
            # Closed so Git's helper processes don't keep the folder open on
            # Windows
            cleanup.callback(overleaf_repo.close)
            # Reread the checkpoint in case a sync we waited on just moved it
            sync_data = calkit.overleaf.get_sync_info().get(
                synced_folder, sync_data
            )
            if resolve:
                last_sync_commit = resolving_info["last_overleaf_commit"]
            else:
                last_sync_commit = sync_data.get("last_sync_commit")
            push = None
            if isinstance(overleaf_auth, calkit.overleaf.WebClient):
                push = partial(
                    calkit.overleaf.push_mirror,
                    client=overleaf_auth,
                    project_id=overleaf_project_id,
                )
            try:
                results[synced_folder] = calkit.overleaf.sync(
                    main_repo=repo,
                    overleaf_repo=overleaf_repo,
                    path_in_project=synced_folder,
                    sync_info_for_path=sync_data,
                    last_sync_commit=last_sync_commit,
                    no_commit=no_commit,
                    verbose=verbose,
                    resolving_conflict=resolve,
                    print_info=typer.echo,
                    push_only=push_only,
                    force=force,
                    push=push,
                    commit_calkit_yaml=not calkit_yaml_dirty,
                )
            except Exception as e:
                raise_error(str(e))
    # Rebuild documents changed on Overleaf or locally so their outputs match
    # the source, without running the stages they depend on unless asked
    doc_stages = _get_document_stages(list(results))
    to_build = {
        folder
        for folder, res in results.items()
        if not push_only
        and (
            res.get("commits_since_last_sync") or res.get("committed_overleaf")
        )
    } | {
        doc_stages[s] for s in readiness["stale_documents"] if s in doc_stages
    }
    build_stages = (
        []
        if no_build
        else [name for name, f in doc_stages.items() if f in to_build]
    )
    built_folders = sorted({doc_stages[name] for name in build_stages})
    built = False
    push_dvc = False
    if build_stages:
        typer.echo("Rebuilding " + ", ".join(build_stages))
        dirty_before = get_dirty_files()
        try:
            calkit_run(targets=build_stages, single_item=not upstream)
        except Exception:
            warn(
                "Rebuilding failed, so only the synced source was saved; "
                "fix the build and run 'calkit run' to rebuild"
            )
        else:
            # Only what the build wrote is saved, leaving other work alone, and
            # stray files next to the document, e.g., aux files no ignore rule
            # covers
            dvc_stages = calkit.dvc.read_pipeline(
                wdir=str(repo.working_dir)
            ).get("stages", {})
            outs = {
                posixpath.normpath(
                    posixpath.join(
                        (dvc_stages.get(name) or {}).get("wdir") or ".", p
                    )
                )
                for name in build_stages
                for p in calkit.dvc.out_paths_from_stage(
                    dvc_stages.get(name) or {}
                )
            }
            dirty_after = get_dirty_files()
            changed = [
                path
                for path, state in dirty_after.items()
                if dirty_before.get(path) != state
                and not (
                    state[1]
                    and any(
                        Path(path).is_relative_to(f) for f in built_folders
                    )
                    and path not in outs
                    and os.path.basename(path) != ".gitignore"
                )
            ]
            # A file with changes from before the build may hold work that
            # isn't the build's, e.g., another stage's entry in dvc.lock.
            # dvc.yaml is generated from calkit.yaml, so it's the build's
            # whenever calkit.yaml is committed.
            kept_out = sorted(
                path
                for path in changed
                if path in dirty_before and path != "dvc.yaml"
            )
            to_save = [
                path
                for path in changed
                if path not in kept_out and path != "dvc.yaml"
            ]
            if "dvc.yaml" in dirty_after and not calkit_yaml_dirty:
                to_save.append("dvc.yaml")
            if kept_out:
                warn(
                    "Left out of the rebuild commit, since they had "
                    "uncommitted changes before it: " + ", ".join(kept_out)
                )
            if to_save:
                repo.git.add("-A", "--", *to_save)
            if to_save and repo.git.diff("--staged", "--", *to_save):
                push_dvc = any(
                    os.path.basename(p) == "dvc.lock" for p in to_save
                )
                if not no_commit:
                    repo.git.commit(
                        "-m",
                        f"Rebuild {', '.join(built_folders)} after Overleaf "
                        "sync",
                        "--",
                        *to_save,
                    )
                    built = True
    if results and not no_push and not no_commit:
        if not repo.remotes:
            raise_error("Project has no Git remotes defined")
        if (
            built
            or edited_folders
            or any(
                res.get("committed_project", True) for res in results.values()
            )
        ):
            # Push to the project remote
            typer.echo("Pushing changes to project Git remote")
            repo.git.push()
        # Built outputs DVC tracks are only recorded in Git by their hash
        if built and push_dvc:
            calkit_push(targets=["dvc"])
    if any(res.get("map_paths_propagated") for res in results.values()) and (
        not (built and upstream)
    ):
        typer.echo(
            "Run 'calkit run' to rebuild from the updated source file(s)"
        )
    return results


def compare_folders_recursively(
    dir1: str, dir2: str, paths: list[str], dirname: str = ""
) -> dict[str, list[str]]:
    """Compare two directories recursively."""
    res = {
        "left_only": [],
        "right_only": [],
        "diff_files": [],
        "same_files": [],
    }
    dcmp = filecmp.dircmp(dir1, dir2)
    for category in ["left_only", "right_only", "diff_files", "same_files"]:
        items = getattr(dcmp, category)
        for item in items:
            relpath = os.path.join(dirname, item)
            if relpath in paths:
                res[category].append(relpath)
    # Recursively compare subdirectories
    for subdir_name, sub_dcmp in dcmp.subdirs.items():
        subdir_res = compare_folders_recursively(
            sub_dcmp.left, sub_dcmp.right, paths=paths, dirname=subdir_name
        )
        for k in res.keys():
            res[k] += subdir_res[k]
    return res


@overleaf_app.command(name="status|st")
def get_status(
    paths: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Paths synced with Overleaf, e.g., 'paper'. "
                "If not provided, all Overleaf syncs will be checked."
            ),
        ),
    ] = None,
):
    """Check the status of folders synced with Overleaf in a project."""
    # Read all synced folders, fixing legacy schema if applicable
    overleaf_info = calkit.overleaf.get_sync_info(fix_legacy=False)
    if not overleaf_info:
        raise_error("No Overleaf sync info found")
    overleaf_sync_dirs = list(overleaf_info.keys())
    if paths is not None:
        paths = [
            (os.path.dirname(p) if os.path.isfile(p) else p)
            .strip()
            .rstrip("/\\")
            for p in paths
        ]
        for path in paths:
            if path not in overleaf_sync_dirs:
                raise_error(f"Path '{path}' is not synced with Overleaf")
    overleaf_auth = _get_overleaf_auth()
    first = True
    for path_in_project, sync_data in overleaf_info.items():
        if paths is not None and path_in_project not in paths:
            continue
        overleaf_project_id = sync_data.get("project_id")
        if not overleaf_project_id:
            raise_error(
                "No Overleaf project ID defined for this folder; "
                "please set it in the project's Overleaf config"
            )
        # Separate each folder's status from the one before
        if not first:
            typer.echo()
        first = False
        folder = typer.style(path_in_project, fg="blue")
        typer.echo(
            f"Getting status of {folder} with "
            f"Overleaf project ID {overleaf_project_id}"
        )
        wdir = path_in_project
        # Keep other processes from using the clone until we're done
        with (
            calkit.overleaf.lock(overleaf_project_id, typer.echo),
            ExitStack() as cleanup,
        ):
            overleaf_project_dir = calkit.overleaf.get_project_dir(
                overleaf_project_id
            )
            typer.echo("Pulling the latest version from Overleaf")
            overleaf_repo, overleaf_auth = _get_pulled_overleaf_repo(
                overleaf_project_id, overleaf_auth
            )
            cleanup.callback(overleaf_repo.close)
            # Reread the checkpoint in case a sync we waited on just moved it
            sync_data = calkit.overleaf.get_sync_info().get(
                path_in_project, sync_data
            )
            last_sync_commit = calkit.overleaf.ensure_sync_base(
                overleaf_repo,
                main_repo=calkit.git.get_repo(),
                path_in_project=path_in_project,
                last_sync_commit=sync_data.get("last_sync_commit"),
                print_info=typer.echo,
                missing_ok=True,
            )
            if last_sync_commit:
                commits_since = calkit.overleaf.get_commits_since_last_sync(
                    overleaf_repo=overleaf_repo,
                    last_sync_commit=last_sync_commit,
                )
                typer.echo(
                    f"There have been {len(commits_since)} changes on "
                    "Overleaf since last sync"
                )
            # Determine which paths to use for computing diff
            path_info = calkit.overleaf.OverleafSyncPaths(
                main_repo=calkit.git.get_repo(),
                overleaf_repo=overleaf_repo,
                path_in_project=path_in_project,
                sync_info_for_path=sync_data,
            )
            status = compare_folders_recursively(
                wdir,
                overleaf_project_dir,
                paths=path_info.all_synced_files,
            )

            def print_path(p, fg_color=None):
                txt = f"    {os.path.join(wdir, p)}"
                typer.echo(typer.style(txt, fg=fg_color))

            if status["left_only"]:
                typer.echo("Files only in Calkit project:")
                for p in status["left_only"]:
                    print_path(p, "green")
            if status["right_only"]:
                typer.echo("Files only in Overleaf project:")
                for p in status["right_only"]:
                    print_path(p, "yellow")
            if status["diff_files"]:
                typer.echo("Changed files:")
                for p in status["diff_files"]:
                    print_path(p, "red")


def _prepare_to_sync(
    branch: str | None,
    yes: bool,
    no_pull: bool,
    allow_stale: bool,
    any_branch: bool,
) -> None:
    """Get the project into a state worth syncing to Overleaf from.

    Switches branches if asked, brings down the latest Git and DVC data,
    then checks the two things that make a sync misleading -- a branch
    behind the trunk and an out-of-date pipeline -- offering to run the
    pipeline when that's what's missing.
    """
    from calkit.cli.main.core import pull as calkit_pull
    from calkit.cli.main.core import run as calkit_run
    from calkit.cli.main.core import switch_branch

    def confirm(message: str) -> bool:
        if yes:
            return True
        return typer.confirm(message, default=True)

    if branch is not None:
        typer.echo(f"Switching to branch '{branch}'")
        switch_branch(branch)
    if not no_pull:
        # A failed pull is usually a transient storage error, and syncing on
        # top of half-fetched data is worse than trying again
        attempts = 0
        while True:
            try:
                # Arg lists are passed explicitly since their defaults are
                # shared mutable lists that force=True appends to
                calkit_pull(force=True, git_args=[], dvc_args=[])
                break
            except Exception as e:
                warn(f"Failed to pull: {e}")
                attempts += 1
                # Retrying is the one prompt --yes can't simply answer yes
                # to, since a pull that keeps failing would loop forever
                # unattended. Bound it instead.
                if yes:
                    if attempts >= _MAX_PULL_ATTEMPTS:
                        raise_error(
                            f"Failed to pull after {attempts} attempts; "
                            "stopping since the project isn't up-to-date"
                        )
                    continue
                if not typer.confirm("Try pulling again?", default=True):
                    if typer.confirm(
                        "Continue without pulling?", default=False
                    ):
                        break
                    raise_error("Stopping since the project isn't up-to-date")
    typer.echo("Checking the project is ready to sync")
    readiness = check_sync_readiness(
        check_branch=not any_branch, check_pipeline=not allow_stale
    )
    if readiness["branch"]:
        raise_error(
            readiness["branch"]
            + ".\nOverleaf has no branches, so syncing from here can send "
            "collaborators a version that's missing work already on the "
            "default branch.\nMerge or rebase first, or use --any-branch to "
            "sync anyway."
        )
    if readiness["pipeline"] and readiness["stale_stages"]:
        warn(readiness["pipeline"])
        if confirm("Run the pipeline now?"):
            calkit_run()
            readiness = check_sync_readiness(check_branch=False)
    if readiness["pipeline"]:
        raise_error(
            readiness["pipeline"]
            + ".\nSyncing now could send stale figures or results to "
            "Overleaf.\nUse --allow-stale to sync anyway."
        )


@overleaf_app.command(name="push")
def push_to_overleaf(
    paths: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Paths to push to Overleaf, e.g., 'paper'. "
                "If not provided, all Overleaf publications will be pushed."
            ),
        ),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option(
            "--branch",
            "-b",
            help="Switch to (or create) this branch before pushing.",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Answer yes to all prompts, e.g., to run non-interactively.",
        ),
    ] = False,
    no_pull: Annotated[
        bool,
        typer.Option(
            "--no-pull", help="Do not pull from Git and DVC beforehand."
        ),
    ] = False,
    allow_stale: Annotated[
        bool,
        typer.Option(
            "--allow-stale",
            help="Push even if the pipeline is out-of-date.",
        ),
    ] = False,
    any_branch: Annotated[
        bool,
        typer.Option(
            "--any-branch",
            help=(
                "Push even if the current branch is missing commits from the "
                "default branch."
            ),
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Overwrite changes made on Overleaf to push-only paths, "
                "which the project is meant to be the source of truth for."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Enable verbose output.")
    ] = False,
) -> None:
    """Get the project's latest figures and text onto Overleaf.

    Pulls the latest data, ensures the pipeline is up-to-date, then pushes
    to Overleaf without pulling anything back, so collaborators see current
    results before they write against them.
    """
    _prepare_to_sync(
        branch=branch,
        yes=yes,
        no_pull=no_pull,
        allow_stale=allow_stale,
        any_branch=any_branch,
    )
    sync(
        paths=paths,
        push_only=True,
        verbose=verbose,
        allow_stale=True,
        any_branch=True,
        force=force,
    )
    calkit.echo("Overleaf is up-to-date with this project ✅")


@overleaf_app.command(name="pull")
def pull_from_overleaf(
    paths: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Paths to pull from Overleaf, e.g., 'paper'. "
                "If not provided, all Overleaf publications will be pulled."
            ),
        ),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option(
            "--branch",
            "-b",
            help=(
                "Switch to (or create) this branch before pulling. Useful "
                "when the default branch is protected, since pulling from "
                "Overleaf creates commits."
            ),
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Answer yes to all prompts, e.g., to run non-interactively.",
        ),
    ] = False,
    no_pull: Annotated[
        bool,
        typer.Option(
            "--no-pull", help="Do not pull from Git and DVC beforehand."
        ),
    ] = False,
    no_run: Annotated[
        bool,
        typer.Option(
            "--no-run", help="Do not run the pipeline after pulling."
        ),
    ] = False,
    allow_stale: Annotated[
        bool,
        typer.Option(
            "--allow-stale",
            help="Pull even if the pipeline is out-of-date.",
        ),
    ] = False,
    any_branch: Annotated[
        bool,
        typer.Option(
            "--any-branch",
            help=(
                "Pull even if the current branch is missing commits from the "
                "default branch."
            ),
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Overwrite changes made on Overleaf to push-only paths, "
                "which the project is meant to be the source of truth for."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Enable verbose output.")
    ] = False,
) -> None:
    """Bring collaborators' Overleaf writing back into the project.

    Syncs in both directions, since Overleaf needs current figures to be
    worth writing against, then rebuilds the document from whatever came
    back and saves it.
    """
    from calkit.cli.main.core import run as calkit_run
    from calkit.cli.main.core import save

    def confirm(message: str) -> bool:
        if yes:
            return True
        return typer.confirm(message, default=True)

    _prepare_to_sync(
        branch=branch,
        yes=yes,
        no_pull=no_pull,
        allow_stale=allow_stale,
        any_branch=any_branch,
    )
    typer.echo("Checking what has changed on Overleaf")
    get_status(paths=paths)
    if not confirm("Continue with the sync?"):
        raise_error("Stopped so the changes above can be reviewed")
    results = sync(
        paths=paths,
        verbose=verbose,
        allow_stale=True,
        any_branch=True,
        force=force,
        no_build=no_run,
    )
    # An Overleaf edit to a map-paths copy lands in the file it's copied
    # from, so the document is only rebuilt from it after a run
    propagated = {
        dest: src
        for res in (results or {}).values()
        for dest, src in (res.get("map_paths_propagated") or {}).items()
    }
    if no_run:
        if propagated:
            warn(
                "Run the pipeline to rebuild from: "
                + ", ".join(sorted(set(propagated.values())))
            )
        return
    status = check_sync_readiness(check_branch=False)
    if not status["pipeline"]:
        typer.echo("Pipeline is up-to-date; nothing to rebuild")
        return
    if not status["stale_stages"]:
        # Something stopped the check from reaching an answer, so there's
        # nothing to offer to run
        warn(status["pipeline"])
        return
    typer.echo(
        "The document needs rebuilding from what came back: "
        + ", ".join(status["stale_stages"])
    )
    if confirm("Run the pipeline now?"):
        calkit_run()
        if confirm("Save and push the rebuilt outputs?"):
            save(save_all=True, message="Run pipeline after Overleaf sync")
