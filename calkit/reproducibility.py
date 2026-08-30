"""Checking how reproducible a project is."""

import os
import posixpath
import re
from typing import Any, Callable

from pydantic import BaseModel, Field, computed_field

import calkit
from calkit.provenance import PROVENANCE_ARTIFACT_TYPES, has_provenance

INSTRUCTIONS_NOTE = (
    "Note that these could be as simple as telling the user to "
    "execute `calkit run`, so long as that will "
    "reproduce everything."
)

# File types that are hard to make by hand. A misc artifact of one of these
# with nothing saying where it came from most likely came out of a script,
# or was exported from an image editor's or office suite's project file,
# and either way there is a stage, an import, or a person to record.
# Plain text formats are left out, since a hand-written config or note is
# its own record.
MISC_EXTENSIONS_NEEDING_PROVENANCE = {
    # Rasters
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".tif",
    ".tiff",
    ".webp",
    ".bmp",
    # Vector and page formats, which are exported rather than typed
    ".svg",
    ".pdf",
    ".eps",
    # Office documents
    ".docx",
    ".pptx",
    ".xlsx",
    ".odt",
    ".odp",
    ".ods",
    # Binary data and archives
    ".h5",
    ".hdf5",
    ".nc",
    ".npy",
    ".npz",
    ".parquet",
    ".pkl",
    ".pickle",
    ".mat",
    ".zip",
    ".tar",
    ".gz",
}

# What counts as a script when looking for ones the pipeline never runs.
SCRIPT_EXTENSIONS = {
    ".py",
    ".sh",
    ".bash",
    ".zsh",
    ".r",
    ".jl",
    ".m",
    ".ipynb",
    ".ps1",
}

# Directories whose scripts belong to tooling rather than to the analysis,
# so their absence from the pipeline says nothing about reproducibility.
# Environment directories are usually gitignored, but not always, e.g.,
# renv keeps its activation script in the repo.
_SCRIPT_DIRS_IGNORED = {
    ".calkit",
    ".devcontainer",
    ".git",
    ".github",
    ".ipynb_checkpoints",
    ".pixi",
    ".venv",
    "node_modules",
    "renv",
    "venv",
}


def _bool_to_check_x(val: bool | int) -> str:
    """Convert a boolean to a checkmark or an X."""
    if val:
        return "✅"
    else:
        return "❌"


class ReproCheck(BaseModel):
    has_pipeline: bool
    has_readme: bool
    instructions_in_readme: bool
    is_dvc_repo: bool
    is_git_repo: bool
    has_calkit_info: bool
    has_dev_container: bool
    n_environments: int
    n_stages: int
    stages_with_env: list[str]
    stages_without_env: list[str]
    n_datasets: int
    n_datasets_no_import_or_stage: int
    n_figures: int
    n_figures_no_import_or_stage: int
    n_publications: int
    n_publications_no_import_or_stage: int
    n_misc: int = 0
    n_misc_no_import_or_stage: int = 0
    # Defaults so a check written before these types were counted still
    # loads
    n_tables: int = 0
    n_tables_no_import_or_stage: int = 0
    n_presentations: int = 0
    n_presentations_no_import_or_stage: int = 0
    # Paths of misc artifacts with no provenance whose file type is one
    # nobody makes by hand, so something should be recorded for them
    misc_needing_provenance: list[str] = []
    # Paths of Git-tracked scripts no pipeline stage refers to, which the
    # pipeline therefore can't be reproducing
    scripts_not_in_pipeline: list[str] = []
    n_dvc_remotes: int
    # Numbers typed into a manuscript that no pipeline output accounts for
    untraceable_literals: list[dict] = Field(default_factory=list)
    # TODO: Check calkit remotes are authenticated

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recommendation(self) -> str | None:
        """Formulate a recommendation for the project."""
        if not self.is_git_repo:
            return "Since this is not a Git repo, run `git init` next."
        if not self.has_readme:
            return (
                "There is no README.md file. "
                "Create one, and ensure it has basic instructions for "
                "reproducing this project's results. " + INSTRUCTIONS_NOTE
            )
        if not self.instructions_in_readme:
            return (
                "The README.md file doesn't contain "
                "basic instructions for reproducing results, "
                "so these should be added next. " + INSTRUCTIONS_NOTE
            )
        if not self.is_dvc_repo:
            return "DVC has not been initialized. Run `dvc init` next."
        if not self.n_dvc_remotes:
            return (
                "No DVC remotes have been defined. "
                "Run `calkit config remote` or `dvc remote add` next."
            )
        if not self.has_pipeline:
            return (
                "There is no DVC pipeline. "
                "Add some stages with `dvc stage add`."
            )
        if not self.has_calkit_info:
            return (
                "There is no `calkit.yaml` file. "
                "Add some artifacts with `calkit new`."
            )
        if self.n_environments == 0:
            return (
                "There are no computational environments defined. "
                "Add one with `calkit new environment`."
            )
        if self.n_stages_without_env > 0:
            return (
                f"There are {self.n_stages_without_env} stages "
                f"({', '.join(self.stages_without_env)}) "
                "with commands "
                "executed outside a defined environment. "
                "Define the environment for those next."
            )
        if self.n_scripts_not_in_pipeline > 0:
            return (
                f"There are {self.n_scripts_not_in_pipeline} scripts "
                f"({', '.join(self.scripts_not_in_pipeline)}) "
                "that no pipeline stage runs, so whatever they produce "
                "can't be reproduced with `calkit run`. Add stages for "
                "them, or remove them if they're no longer used."
            )
        # These are a subset of the misc artifacts flagged below, but the
        # more pointed finding comes first: a PNG with nothing recorded
        # almost certainly came out of a script or an editor's project file
        if self.n_misc_needing_provenance > 0:
            return (
                f"There are {self.n_misc_needing_provenance} misc "
                f"artifacts ({', '.join(self.misc_needing_provenance)}) "
                "of a kind that isn't made by hand, with no provenance "
                "recorded. Add the stage that produces them, the project "
                "file they were exported from, or who created them."
            )
        for artifact_type in PROVENANCE_ARTIFACT_TYPES:
            n_bad = getattr(self, f"n_{artifact_type}_no_import_or_stage")
            if n_bad:
                return (
                    f"There are {n_bad} {artifact_type} with no provenance "
                    "recorded: neither produced by a pipeline stage, nor "
                    "imported, nor attributed to whoever collected or "
                    "created them. Define where they came from or create "
                    "stage(s) to produce them."
                )
        if not self.has_dev_container:
            return (
                "No dev container spec is defined. "
                "Create one with `calkit update devcontainer`."
            )
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_datasets_with_import_or_stage(self) -> int:
        return self.n_datasets - self.n_datasets_no_import_or_stage

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_figures_with_import_or_stage(self) -> int:
        return self.n_figures - self.n_figures_no_import_or_stage

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_publications_with_import_or_stage(self) -> int:
        return self.n_publications - self.n_publications_no_import_or_stage

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_misc_with_import_or_stage(self) -> int:
        return self.n_misc - self.n_misc_no_import_or_stage

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_tables_with_import_or_stage(self) -> int:
        return self.n_tables - self.n_tables_no_import_or_stage

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_presentations_with_import_or_stage(self) -> int:
        return self.n_presentations - self.n_presentations_no_import_or_stage

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_misc_needing_provenance(self) -> int:
        return len(self.misc_needing_provenance)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_scripts_not_in_pipeline(self) -> int:
        return len(self.scripts_not_in_pipeline)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_stages_without_env(self) -> int:
        return len(self.stages_without_env)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n_stages_with_env(self) -> int:
        return len(self.stages_with_env)

    def to_pretty(self) -> str:
        """Format as a nice string to print."""
        txt = f"Is a Git repo: {_bool_to_check_x(self.is_git_repo)}\n"
        txt += f"Has README.md: {_bool_to_check_x(self.has_readme)}\n"
        txt += (
            f"Instructions in README.md: "
            f"{_bool_to_check_x(self.instructions_in_readme)}\n"
        )
        txt += f"DVC initialized: {_bool_to_check_x(self.is_dvc_repo)}\n"
        txt += f"DVC remote defined: {_bool_to_check_x(self.n_dvc_remotes)}\n"
        txt += f"Has pipeline: {_bool_to_check_x(self.has_pipeline)}\n"
        txt += f"Has Calkit info: {_bool_to_check_x(self.has_calkit_info)}\n"
        txt += (
            f"Has dev container spec: "
            f"{_bool_to_check_x(self.has_dev_container)}\n"
        )
        txt += (
            f"Environments defined: {self.n_environments} "
            f"{_bool_to_check_x(self.n_environments)}\n"
        )
        txt += (
            "Pipeline stages run in an environment: "
            f"{self.n_stages_with_env}/{self.n_stages} "
            f"{_bool_to_check_x(self.n_stages_without_env == 0)}\n"
        )
        txt += (
            "Scripts not run by any pipeline stage: "
            f"{self.n_scripts_not_in_pipeline} "
            f"{_bool_to_check_x(self.n_scripts_not_in_pipeline == 0)}\n"
        )
        for artifact_type in PROVENANCE_ARTIFACT_TYPES:
            n = getattr(self, f"n_{artifact_type}")
            n_bad = getattr(self, f"n_{artifact_type}_no_import_or_stage")
            n_good = getattr(self, f"n_{artifact_type}_with_import_or_stage")
            txt += (
                f"{artifact_type.capitalize()} with provenance recorded "
                f"(stage, import, or attribution): {n_good}/{n} "
                f"{_bool_to_check_x(n_bad == 0)}\n"
            )
        txt += (
            "Misc artifacts not made by hand but lacking provenance: "
            f"{self.n_misc_needing_provenance} "
            f"{_bool_to_check_x(self.n_misc_needing_provenance == 0)}\n"
        )
        if self.untraceable_literals:
            txt += (
                f"Untraceable literals: {len(self.untraceable_literals)} "
                f"{_bool_to_check_x(False)}\n"
            )
        else:
            txt += f"Untraceable literals: 0 {_bool_to_check_x(True)}\n"
        if self.recommendation:
            txt += f"\nRecommendation: {self.recommendation}\n"
        return txt


def _strings_in(obj: object) -> list[str]:
    """Every string anywhere inside a nested dict/list structure."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings_in(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings_in(v)]
    return []


def find_scripts_not_in_pipeline(
    wdir: str = ".", ck_info: dict | None = None, pipeline: dict | None = None
) -> list[str]:
    """Return Git-tracked scripts that no pipeline stage refers to.

    A stage refers to a script by naming it anywhere in its definition:
    as its script or notebook, in its command, or among its inputs or
    dependencies. Both the DVC pipeline and the Calkit one are searched,
    since a stage declared in calkit.yaml may not have been compiled to
    dvc.yaml yet. Only tracked files are walked, which keeps this cheap and
    leaves out anything gitignored. Files under tooling and environment
    directories, and environment files themselves, are not scripts of the
    analysis and are skipped.
    """
    from git.exc import InvalidGitRepositoryError

    try:
        repo = calkit.git.get_repo(wdir)
    except InvalidGitRepositoryError:
        return []
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    if pipeline is None:
        pipeline = calkit.dvc.read_pipeline(wdir=wdir)
    env_paths = {
        posixpath.normpath(env["path"])
        for env in ck_info.get("environments", {}).values()
        if isinstance(env, dict) and env.get("path")
    }
    env_prefixes = {
        posixpath.normpath(env["prefix"])
        for env in ck_info.get("environments", {}).values()
        if isinstance(env, dict) and env.get("prefix")
    }
    # One string to search rather than a set of paths, since a command
    # names its script somewhere inside it and a dependency may be written
    # with a leading ./
    referenced = "\n".join(
        _strings_in(pipeline.get("stages", {}))
        + _strings_in(ck_info.get("pipeline", {}))
    )
    # Tracked paths are relative to the repo root, which may be above wdir
    # when checking a subproject, so make them relative to wdir
    root = os.path.abspath(repo.working_dir)
    wdir_abs = os.path.abspath(wdir)
    prefix = os.path.relpath(wdir_abs, root).replace(os.sep, "/")
    prefix = "" if prefix == "." else prefix + "/"
    scripts = []
    for path in calkit.git.ls_files(repo):
        if not path.startswith(prefix):
            continue
        path = path[len(prefix) :]
        if posixpath.splitext(path)[1].lower() not in SCRIPT_EXTENSIONS:
            continue
        parts = path.split("/")
        if any(p in _SCRIPT_DIRS_IGNORED for p in parts[:-1]):
            continue
        if path in env_paths or any(
            path == p or path.startswith(p + "/") for p in env_prefixes
        ):
            continue
        if path not in referenced:
            scripts.append(path)
    return scripts


def _mask_match(match: re.Match) -> str:
    """Whitespace as long as what matched.

    Blanking rather than deleting, so every later match still reports the
    line and column it has in the real file.
    """
    return " " * len(match.group(0))


def _mask_exclusion_zones(tex_source: str) -> str:
    """Mask out LaTeX constructs where numeric literals should be ignored."""
    masked = tex_source
    # Comments: % to end of line, but not an escaped \%
    masked = re.sub(r"(?<!\\)%.*$", _mask_match, masked, flags=re.MULTILINE)
    # Environments whose contents are never results
    environments_to_mask = ["thebibliography"]
    for env in environments_to_mask:
        # Match \begin{env} ... \end{env} across multiple lines
        pattern = (
            r"\\begin\{"
            + re.escape(env)
            + r"\}.*?\\end\{"
            + re.escape(env)
            + r"\}"
        )
        masked = re.sub(pattern, _mask_match, masked, flags=re.DOTALL)
    # Macros whose arguments are references, layout, or links rather than
    # anything computed
    macros_to_mask = [
        r"\\cite[a-zA-Z]*\*?\{[^}]*\}",
        r"\\bibitem\{[^}]*\}",
        r"\\href\{[^}]*\}\{[^}]*\}",
        r"\\url\{[^}]*\}",
        r"\\doi\{[^}]*\}",
        r"\\ref\{[^}]*\}",
        r"\\eqref\{[^}]*\}",
        r"\\pageref\{[^}]*\}",
        r"\\label\{[^}]*\}",
        r"\\input\{[^}]*\}",
        r"\\include\{[^}]*\}",
        r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}",
        r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\}",
        r"\\setlength\{[^}]*\}\{[^}]*\}",
        r"\\vspace\*?\{[^}]*\}",
        r"\\hspace\*?\{[^}]*\}",
        r"\\geometry\{[^}]*\}",
        r"\\multicolumn\{[^}]*\}\{[^}]*\}\{[^}]*\}",
    ]
    for macro_pattern in macros_to_mask:
        masked = re.sub(macro_pattern, _mask_match, masked, flags=re.DOTALL)
    # Bare DOIs
    masked = re.sub(r"10\.\d{4,}/[^\s]+", _mask_match, masked)
    # Years, 1500 to 2100
    masked = re.sub(r"\b(1[5-9]\d{2}|20\d{2}|2100)\b", _mask_match, masked)
    # Page ranges, e.g., 123--145 and pp. 123
    masked = re.sub(r"\b\d+\s*--\s*\d+\b", _mask_match, masked)
    masked = re.sub(r"\bpp\.\s*\d+\b", _mask_match, masked)
    return masked


def find_untraceable_literals(
    tex_source: str,
    filepath: str,
    from_json_values: set[str] | dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """Scan LaTeX source for hardcoded numeric literals not traceable to a pipeline output.

    Parameters
    ----------
    tex_source : str
        The contents of the LaTeX file to scan.
    filepath : str
        The path of the LaTeX file (used for reporting).
    from_json_values : set[str] | dict[str, str] | None
        Traceable string values (or dict mapping value to macro name) that the pipeline produces.
        Any matched literal corresponding to one of these values will not be flagged.

    Returns
    -------
    list[dict[str, Any]]
        A list of findings. Each finding is a dictionary with keys:
        - value: the matched literal string
        - file: the filepath
        - line: 1-indexed line number
        - column: 1-indexed column number
        - context: the surrounding text snippet
        - reason: explanation of why it was flagged
        - suggestion: fix instructions
    """
    from_json: dict[str, str | None]
    if from_json_values is None:
        from_json = {}
    elif isinstance(from_json_values, set):
        from_json = {v: None for v in from_json_values}
    else:
        from_json = from_json_values
    findings = []
    masked_source = _mask_exclusion_zones(tex_source)
    # What a result looks like, most specific first, so a value with
    # uncertainty is read whole rather than as a bare decimal. Group 1 is
    # the literal itself.
    result_like_patterns = [
        # Values with uncertainty, e.g., 0.42 \pm 0.03
        r"(\b\d+(?:\.\d+)?\s*\\pm\s*\d+(?:\.\d+)?\b)",
        # Scientific notation, e.g., 1.2e-3 and 1.2\times10^{-3}
        r"(\b\d+(?:\.\d+)?(?:[eE][+-]?\d+|\s*\\times\s*10\^\{?[+-]?\d+\}?)(?!\d))",
        # Percentages, e.g., 12.7\%
        r"(\b\d+(?:\.\d+)?\s*\\%)",
        # Plain decimals, e.g., 0.42
        r"(\b\d+\.\d+\b)",
    ]
    # Searched one pattern at a time rather than combined, so an earlier,
    # more specific pattern claims its span and a later one can't re-report
    # part of the same literal
    matched_intervals: list[tuple[int, int]] = []

    def is_overlapping(start: int, end: int) -> bool:
        for s, e in matched_intervals:
            if max(start, s) < min(end, e):
                return True
        return False

    lines = tex_source.splitlines()
    for pattern in result_like_patterns:
        for match in re.finditer(pattern, masked_source):
            start, end = match.span(1)
            if is_overlapping(start, end):
                continue
            matched_intervals.append((start, end))
            matched_str = match.group(1).strip()
            # A value the project computes is accounted for, whatever
            # spacing the document wrote it with
            cmp_str = matched_str.replace(" ", "")
            if any(
                cmp_str == tracked.replace(" ", "") for tracked in from_json
            ):
                continue
            # Where it is, counted on the unmasked source so the position
            # is the one someone opening the file will see
            preceding = tex_source[:start]
            line_idx = preceding.count("\n")
            col_idx = (
                len(preceding) - preceding.rfind("\n") - 1
                if "\n" in preceding
                else len(preceding)
            )
            context = lines[line_idx].strip() if line_idx < len(lines) else ""
            findings.append(
                {
                    "value": matched_str,
                    "file": filepath,
                    "line": line_idx + 1,
                    "column": col_idx + 1,
                    "context": context,
                    "reason": (
                        "result-like decimal not traceable to a pipeline "
                        "output"
                    ),
                    "suggestion": (
                        "Compute this in a pipeline stage, write it to a "
                        "results JSON file, add a 'json-to-latex' stage "
                        "over that file, and reference the generated "
                        "command instead of typing the number."
                    ),
                }
            )
    # In the order someone reads the file
    findings.sort(key=lambda x: (x["line"], x["column"]))
    return findings


def _traceable_values(wdir: str, stages: dict) -> set[str]:
    """Every value a ``json-to-latex`` stage puts within the document's reach.

    Read from the results files those stages consume rather than from the
    LaTeX they generate: the results file is what the value actually is,
    and the generated commands are one rendering of it.
    """
    import json

    values: set[str] = set()
    for stage in stages.values():
        cmd = stage.get("cmd", "") or stage.get("do", {}).get("cmd", "")
        if "calkit latex from-json" not in cmd:
            continue
        for dep in stage.get("deps", []) or []:
            if not str(dep).endswith(".json"):
                continue
            try:
                with open(os.path.join(wdir, str(dep))) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                for value in data.values():
                    if isinstance(value, (int, float, str)):
                        values.add(str(value))
    return values


def _generated_tex_paths(wdir: str, stages: dict) -> set[str]:
    """LaTeX files the pipeline writes, which are not manuscripts."""
    paths: set[str] = set()
    for stage in stages.values():
        cmd = stage.get("cmd", "") or stage.get("do", {}).get("cmd", "")
        if "calkit latex from-" not in cmd:
            continue
        for out in stage.get("outs", []) or []:
            out_path = out if isinstance(out, str) else next(iter(out))
            if str(out_path).endswith(".tex"):
                paths.add(os.path.abspath(os.path.join(wdir, str(out_path))))
    return paths


def _tex_sources(wdir: str, ck_info: dict, stages: dict) -> set[str]:
    """Every LaTeX file a manuscript is made of, following its inputs."""
    targets: set[str] = set()
    for pub in ck_info.get("publications", []) or []:
        path = pub.get("path", "") if isinstance(pub, dict) else ""
        if str(path).endswith(".tex"):
            targets.add(str(path))
    for stage in stages.values():
        cmd = stage.get("cmd", "") or stage.get("do", {}).get("cmd", "")
        if "calkit latex build" not in cmd:
            continue
        for dep in stage.get("deps", []) or []:
            if str(dep).endswith(".tex"):
                targets.add(str(dep))
    found: set[str] = set()

    def walk(rel: str) -> None:
        full = os.path.abspath(os.path.join(wdir, rel))
        if full in found or not os.path.isfile(full):
            return
        found.add(full)
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return
        for match in re.finditer(r"\\(?:input|include)\{([^}]+)\}", content):
            child = match.group(1)
            if not child.endswith(".tex"):
                child += ".tex"
            walk(
                os.path.relpath(
                    os.path.join(os.path.dirname(full), child), wdir
                )
            )

    for target in targets:
        walk(target)
    return found


def find_untraceable_literals_in_project(
    wdir: str, ck_info: dict, stages: dict
) -> list[dict]:
    """Numbers typed into a manuscript that no pipeline output accounts for.

    A result typed into prose is a number nobody can check, and it goes
    stale the moment the stage behind it reruns. This reads the manuscript
    and everything it inputs, skipping the files the pipeline generates,
    and reports what it finds that no results file explains.
    """
    traceable = _traceable_values(wdir, stages)
    generated = _generated_tex_paths(wdir, stages)
    findings: list[dict] = []
    for path in sorted(_tex_sources(wdir, ck_info, stages) - generated):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        findings += find_untraceable_literals(
            content, os.path.relpath(path, wdir), traceable
        )
    return findings


def check_reproducibility(
    wdir: str = ".", log_func: Callable | None = None
) -> ReproCheck:
    """Check the reproducibility of a project."""
    from git.exc import InvalidGitRepositoryError

    res: dict = dict()
    if log_func is None:
        log_func = print
    try:
        calkit.git.get_repo(wdir)
        res["is_git_repo"] = True
    except InvalidGitRepositoryError:
        res["is_git_repo"] = False
    res["is_dvc_repo"] = os.path.isfile(os.path.join(wdir, ".dvc", "config"))
    res["has_pipeline"] = os.path.isfile(os.path.join(wdir, "dvc.yaml"))
    res["has_calkit_info"] = os.path.isfile(os.path.join(wdir, "calkit.yaml"))
    res["has_dev_container"] = os.path.isfile(
        os.path.join(wdir, ".devcontainer", "devcontainer.json")
    )
    # Check README for at least minimal instructions
    readme_path = os.path.join(wdir, "README.md")
    if os.path.isfile(readme_path):
        res["has_readme"] = True
        with open(readme_path, encoding="utf-8") as f:
            readme_txt = f.read().lower()
        res["instructions_in_readme"] = (
            ("getting started" in readme_txt)
            or ("instructions" in readme_txt)
            or ("how to run" in readme_txt)
            or ("how to reproduce" in readme_txt)
            or ("calkit" in readme_txt)
        )
    else:
        res["has_readme"] = False
        res["instructions_in_readme"] = False
    ck_info = calkit.load_calkit_info(wdir=wdir)
    pipeline = calkit.dvc.read_pipeline(wdir=wdir)
    # Check for artifacts with no provenance recorded
    for artifact_type in PROVENANCE_ARTIFACT_TYPES:
        artifacts = ck_info.get(artifact_type, [])
        res[f"n_{artifact_type}"] = len(artifacts)
        res[f"n_{artifact_type}_no_import_or_stage"] = len(
            [a for a in artifacts if not has_provenance(a)]
        )
    res["misc_needing_provenance"] = [
        a["path"]
        for a in ck_info.get("misc", [])
        if a.get("path")
        and not has_provenance(a)
        and posixpath.splitext(a["path"])[1].lower()
        in MISC_EXTENSIONS_NEEDING_PROVENANCE
    ]
    res["scripts_not_in_pipeline"] = find_scripts_not_in_pipeline(
        wdir=wdir, ck_info=ck_info, pipeline=pipeline
    )
    res["n_environments"] = len(ck_info.get("environments", {}))
    # Check for stages not run with environments
    stages = pipeline.get("stages", {})
    res["n_stages"] = len(stages)
    stages_no_env = []
    stages_with_env = []
    for stage_name, stage in stages.items():
        if "foreach" in stage:
            cmd = stage.get("do", {}).get("cmd", "")
        else:
            cmd = stage.get("cmd", "")
        if (
            "calkit" not in cmd
            and "conda run" not in cmd
            and "mamba run" not in cmd
            and "docker run" not in cmd
            and "renv::restore()" not in cmd
        ):
            stages_no_env.append(stage_name)
        else:
            stages_with_env.append(stage_name)
    res["stages_without_env"] = stages_no_env
    res["stages_with_env"] = stages_with_env
    # DVC remotes
    dvc_remotes = calkit.dvc.get_remotes(wdir=wdir)
    res["n_dvc_remotes"] = len(dvc_remotes)
    res["untraceable_literals"] = find_untraceable_literals_in_project(
        wdir=wdir, ck_info=ck_info, stages=stages
    )
    return ReproCheck.model_validate(res)
