"""Build the history arms by replaying one research history in each.

Every arm goes through the same research steps, on the same dates, with
the same analysis decisions and results; what differs is how each keeps
that history:

- messy: a plain folder, no Git. Old versions survive only as copies
  (`prepare_data_old.py`, `analysis_v2.ipynb`, dated drafts, cached CSVs)
  and file modification times; `utils.py` was edited in place.
- messy-git: the same folder in Git, committed in terse, bundled commits.
  Copies a Git user would still make stay (notebook copies, cached CSVs,
  named figures, the submitted draft); the dated first draft and
  `prepare_data_old.py` don't exist, since Git holds them.
- make: scripts, a Makefile, and a generated report, committed one change
  per commit with descriptive messages, the submission tagged.
- calkit: the same as make, but a Calkit pipeline instead of the Makefile.

The history (`STEPS`):

1. 2026-03-02: original data arrive; first analysis (ages 60–80, ANCOVA
   without education, Figure 1 with standard-error bars).
2. 2026-03-04: exploratory notebook (make, calkit; the messy arms explore
   in their notebooks).
3. 2026-03-09: first draft.
4. 2026-03-16: education added to both models.
5. 2026-03-23: manuscript submitted.
6. 2026-04-14: corrected sessions export (week-12 form B rescored).
7. 2026-05-04: reviewers: eligible ages widened to 60–85, and Figure 1
   shows 95% CIs.
8. 2026-05-04: rerun and draft updated (the stale variants stop before
   this).
9. 2026-05-11: response to reviewers.
10. 2026-05-18: conference abstract, with the main effect typed in.

The end state's analysis is round 2's: the same table, results, figure,
and report numbers as the none arm.

Usage: python build/build_history.py <arm> <dest>
    [--stale] [--calkit CMD]
"""

import argparse
import copy
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import nbformat
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HIST = HERE / "history"
SHARED = HERE / "shared"
sys.path.insert(0, str(ROOT / "bench"))
import arms  # noqa: E402

PY = sys.executable
# Calkit's record of the machine each stage ran on, the same in every build
BUILD_MACHINE_ID = "00000000-0000-0000-0000-000000000000"
PACKAGES = (
    "numpy==2.5.5 pandas==3.1.1 statsmodels==0.15.0 matplotlib==3.11.2"
).split()
SESSIONS_V1 = "data/raw/sessions_2026-03-02.csv"
SESSIONS_V2 = "data/raw/sessions_2026-04-14_corrected.csv"
FIGURE_CONSTANTS = """WEEKS = [0, 4, 8, 12]
ARMS = {"training": ("Training", "#257de0"), "control": ("Control", "#f47230")}
DODGE = {"training": 0.15, "control": -0.15}"""


def at(stamp: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(stamp)


def get_figure_cell(out: str, ci: bool, table: str = "df") -> str:
    """Figure 1's code as a notebook cell, the same as make_figure.py's."""
    text = (SHARED / "make_figure.py").read_text()
    body = text.split("    fig, ax = plt.subplots(figsize=(5.5, 3.6))\n")[1]
    body = body.split("    fig.savefig(")[0]
    lines = ["fig, ax = plt.subplots(figsize=(5.5, 3.6))"]
    for line in body.splitlines():
        lines.append(line[4:] if line.startswith("    ") else line)
    code = "\n".join(lines).rstrip()
    code = code.replace("df[df[", f"{table}[{table}[")
    if not ci:
        code = code.replace("half = 1.96 * sub.sem()", "half = sub.sem()")
    return (
        code
        + f'\nfig.savefig("{out}", dpi=150, metadata={{"Software": None}})'
    )


def get_report_template(max_age: int, education: bool, ci: bool) -> str:
    """The manuscript's text at a point in the history."""
    text = (SHARED / "report_template.md").read_text()
    text = text.replace("aged 60–85", f"aged 60–{max_age}")
    if not education:
        old = (
            "least squares model of week-12 score on arm, baseline score,"
            " age (per 10\nyears), and education (secondary, college, or"
            " graduate, with secondary as\nthe reference category). As a"
            " sensitivity analysis, we modeled the change in\nscore from"
            " baseline to week 12 on arm, age, and education."
        )
        new = (
            "least squares model of week-12 score on arm, baseline score,"
            " and age (per\n10 years). As a sensitivity analysis, we"
            " modeled the change in score from\nbaseline to week 12 on arm"
            " and age."
        )
        assert old in text
        text = text.replace(old, new)
        lines = []
        for line in text.splitlines(keepends=True):
            if line.startswith("6. "):
                continue
            if line.startswith("7. "):
                line = "6. " + line[3:]
            elif line.startswith("8. "):
                line = "7. " + line[3:]
            lines.append(line)
        text = "".join(lines)
    if not ci:
        old = "Error bars are 95% confidence intervals."
        assert old in text
        text = text.replace(old, "Error bars are standard errors.")
    return text


def format_report(template: str, ancova: dict, change: dict, figure: str):
    """The report as write_report.py writes it, or a person types it."""
    extra = {}
    if "graduate_p" in ancova:
        extra["graduate_p_text"] = format_p(ancova["graduate_p"])
    return template.format(
        **ancova,
        **extra,
        treatment_p_text=format_p(ancova["treatment_p"]),
        change_treatment_effect=change["treatment_effect"],
        change_treatment_ci_low=change["treatment_ci_low"],
        change_treatment_ci_high=change["treatment_ci_high"],
        change_treatment_p_text=format_p(change["treatment_p"]),
        r_squared_pct=100 * ancova["r_squared"],
        figure=figure,
    )


def format_p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.2g}"


def format_abstract(ancova: dict) -> str:
    return (
        (HIST / "abstract.md")
        .read_text()
        .format(**ancova, treatment_p_text=format_p(ancova["treatment_p"]))
    )


def get_utils(max_age: int) -> str:
    return (HIST / "utils.py").read_text().replace("@MAX_AGE@", str(max_age))


def get_flat_prepare(sessions: str, out: str) -> str:
    text = (HIST / "prepare_data_flat.py").read_text()
    return text.replace("@SESSIONS@", sessions).replace("@OUT@", out)


def fit_table(table: Path, education: bool) -> dict:
    """Both models' results for a table, from the arm's own fit_model.py."""
    script = SHARED / "fit_model.py" if education else HIST / "fit_model_v1.py"
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for adjustment in ["ancova", "change"]:
            path = Path(tmp) / f"{adjustment}.json"
            run(
                [
                    PY,
                    "-W",
                    "ignore",
                    str(script),
                    "--data",
                    str(table),
                    "--adjustment",
                    adjustment,
                    "--out",
                    str(path),
                ],
                Path(tmp),
            )
            out[adjustment] = json.loads(path.read_text())
    return out


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> str:
    p = subprocess.run(
        cmd, cwd=cwd, env=env or ENV, capture_output=True, text=True
    )
    if p.returncode != 0:
        raise RuntimeError(f"{cmd} failed in {cwd}:\n{p.stdout}\n{p.stderr}")
    return p.stdout


def get_env(scratch: Path) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONPATH"}
    }
    env["PATH"] = f"{Path(PY).parent}{os.pathsep}{env['PATH']}"
    for name in ["JUPYTER_DATA_DIR", "JUPYTER_RUNTIME_DIR", "IPYTHONDIR"]:
        env[name] = str(scratch / name.lower())
    env["JUPYTER_CONFIG_DIR"] = str(scratch / "jupyter_config_dir")
    env["MPLCONFIGDIR"] = str(scratch / "mplconfig")
    env["PYTHONWARNINGS"] = "ignore"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(arms.get_git_identity_env(arms.BUILDER))
    return env


ENV: dict = {}


def make_notebook(cells: list[tuple[str, str]]) -> nbformat.NotebookNode:
    nb = nbformat.v4.new_notebook()
    nb.metadata = {
        "kernelspec": {
            "display_name": "Python 3 (ipykernel)",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python"},
    }
    for kind, source in cells:
        if kind == "md":
            nb.cells.append(nbformat.v4.new_markdown_cell(source))
        else:
            nb.cells.append(nbformat.v4.new_code_cell(source))
    for i, cell in enumerate(nb.cells):
        cell["id"] = f"cell-{i}"
    return nb


def execute(nb: nbformat.NotebookNode, cwd: Path) -> nbformat.NotebookNode:
    nb = copy.deepcopy(nb)
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(ENV)
    try:
        NotebookClient(
            nb,
            kernel_name="python3",
            resources={"metadata": {"path": str(cwd)}},
            record_timing=False,
            timeout=600,
        ).execute()
    finally:
        os.environ.clear()
        os.environ.update(old)
    return nb


def write_notebook(nb: nbformat.NotebookNode, path: Path) -> None:
    nb.metadata.pop("widgets", None)
    nbformat.write(nb, path)


def set_counts(nb: nbformat.NotebookNode, counts: list[int | None]) -> None:
    """Make a notebook look run out of order, as a person ran it."""
    code = [c for c in nb.cells if c.cell_type == "code"]
    assert len(code) == len(counts), (len(code), counts)
    for cell, n in zip(code, counts):
        cell.execution_count = n
        for out in cell.outputs:
            if "execution_count" in out:
                out["execution_count"] = n


def get_analysis_cells(
    table: str, education: bool, figure: str, dead_ends: bool
) -> list[tuple[str, str]]:
    """The messy arms' main analysis notebook, analysis(_v2).ipynb."""
    edu = " + C(education)" if education else ""
    imports = (
        "import matplotlib.pyplot as plt\nimport pandas as pd\n"
        "import statsmodels.formula.api as smf\n"
    )
    if education:
        imports += "\nfrom utils import format_p\n"
    cells = [
        (
            "md",
            "# Main analysis\n\nModels and Figure 1, from the merged table"
            " prepare_data.py makes."
            + (
                "\n\nv2: adjusted for education, per co-authors' comments."
                if education
                else ""
            ),
        ),
        ("code", imports + "\n" + FIGURE_CONSTANTS),
        ("code", f'df = pd.read_csv("{table}")\ndf.shape'),
        (
            "code",
            "print(f\"N = {len(df)}, mean age {df['age'].mean():.1f},"
            " {100 * (df['sex'] == 'F').mean():.0f}% women\")",
        ),
        (
            "code",
            'df.groupby("arm")[["score_w0", "score_w12"]].mean().round(1)',
        ),
        (
            "code",
            "def show(fit):\n    ci = fit.conf_int()\n    return pd.DataFrame(\n"
            '        {"coef": fit.params, "ci_low": ci[0], "ci_high": ci[1],'
            ' "p": fit.pvalues}\n    ).round(4)\n\n\n'
            "ancova = smf.ols(\n"
            f'    "score_w12 ~ treated + score_w0 + I(age / 10){edu}", data=df\n'
            ").fit()\n"
            'print(f"R2 = {ancova.rsquared:.3f}")\n'
            + (
                'print(format_p(ancova.pvalues["treated"]))\n'
                if education
                else ""
            )
            + "show(ancova)",
        ),
        (
            "code",
            "change = smf.ols(\n"
            f'    "I(score_w12 - score_w0) ~ treated + I(age / 10){edu}", data=df\n'
            ").fit()\nshow(change)",
        ),
    ]
    if dead_ends:
        cells += [
            ("code", '# does site matter?\ndf.groupby("site").size()'),
            (
                "code",
                "# try complete cases only (all four weeks)\n"
                'clean = df.dropna(subset=["score_w4", "score_w8"])\n'
                'clean.to_csv("data/merged_clean.csv", index=False)\n'
                "smf.ols(\n"
                '    "score_w12 ~ treated + score_w0 + I(age / 10)",'
                " data=clean\n"
                ').fit().params["treated"]',
            ),
        ]
    cells.append(("code", get_figure_cell(figure, ci=False)))
    return cells


def get_final_cells(ci: bool) -> list[tuple[str, str]]:
    """The messy arms' figure notebook, analysis_v2_final.ipynb."""
    return [
        ("md", "# Figure 1 (final)\n\nWith the corrected sessions export."),
        (
            "code",
            "import matplotlib.pyplot as plt\nimport pandas as pd\n\n"
            + FIGURE_CONSTANTS,
        ),
        ("code", 'df = pd.read_csv("data/merged_final.csv")\ndf.shape'),
        ("code", 'len(df), df["age"].min(), df["age"].max()'),
        (
            "code",
            get_figure_cell("figures/fig1_FINAL_revised.png", ci=ci),
        ),
    ]


def get_explore_cells() -> list[tuple[str, str]]:
    """The careful arms' exploratory notebook, outside the pipeline."""
    return [
        (
            "md",
            "# Exploration\n\nQuick looks at the analysis table; not part of"
            " the analysis.",
        ),
        (
            "code",
            "import pandas as pd\nimport statsmodels.formula.api as smf\n\n"
            'df = pd.read_csv("../data/analysis.csv")\ndf.shape',
        ),
        ("code", 'df.groupby("site").size()'),
        ("code", 'df["age"].describe().round(1)'),
        (
            "code",
            "# does the effect hold in complete cases?\n"
            'clean = df.dropna(subset=["score_w4", "score_w8"])\n'
            'smf.ols("score_w12 ~ treated + score_w0", data=clean).fit()'
            '.params["treated"]',
        ),
        ("code", "# TODO: mixed model over all weeks?"),
    ]


class History:
    """Replays the steps in one arm, stamping files with each step's time."""

    def __init__(self, arm: str, dest: Path, stale: bool, calkit: str):
        self.arm = arm
        self.dest = dest
        self.stale = stale
        self.calkit = shlex.split(calkit)
        self.git = arm != "messy"
        ENV.clear()
        ENV.update(get_env(Path(tempfile.mkdtemp(prefix="history-state-"))))
        self.data = Path(tempfile.mkdtemp(prefix="history-data-"))
        run(
            [
                PY,
                "-W",
                "ignore",
                str(HERE / "generate_data.py"),
                "--out-dir",
                str(self.data),
            ],
            HERE,
        )
        self.when = at("2026-03-02T09:00:00")
        self.keep_mtime: set[str] = set()

    def stamp(self, before: dict) -> None:
        """Give the files a step wrote that step's time."""
        t = self.when.timestamp()
        for f in arms.list_files(self.dest):
            path = self.dest / f
            if f in self.keep_mtime:
                continue
            if before.get(f) != path.stat().st_mtime_ns:
                os.utime(path, (t, t))
        for d in [self.dest, *self.dest.rglob("*")]:
            skip = {".git", ".venv", ".dvc"}
            if d.is_dir() and not skip & set(d.relative_to(self.dest).parts):
                os.utime(d, (t, t))

    def step(self, when: str, fn, *args) -> None:
        self.when = at(when)
        before = arms.get_mtimes(self.dest) if self.dest.exists() else {}
        fn(*args)
        self.stamp(before)

    def git_env(self) -> dict:
        stamp = self.when.isoformat()
        return {**ENV, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}

    def commit(self, message: str, paths: list[str] | None = None) -> None:
        env = self.git_env()
        run(["git", "add", "-A", *(paths or [])], self.dest, env)
        run(["git", "commit", "-q", "-m", message], self.dest, env)

    def tag(self, name: str, message: str) -> None:
        run(
            ["git", "tag", "-a", name, "-m", message],
            self.dest,
            self.git_env(),
        )

    def write(self, rel: str, text: str) -> None:
        path = self.dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def copy(self, src: Path, rel: str) -> None:
        path = self.dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, path)

    def calkit_run(self, *args: str) -> str:
        return run([*self.calkit, *args], self.dest, self.git_env())

    def date_stage_runs(self) -> None:
        """Date Calkit's record of the run just made at this step's time.

        Calkit records when each stage ran and on which machine, and the
        record is committed, so without this, every build would differ.
        """
        path = self.dest / ".calkit/stage-runs.json"
        runs = json.loads(path.read_text())
        stamp = (
            self.when.astimezone(datetime.timezone.utc)
            .replace(tzinfo=None)
            .isoformat(timespec="microseconds")
        )
        for record in runs.values():
            if record["git_rev"] != self.head():
                continue
            record["start_time"] = record["end_time"] = stamp
            record["system"]["machine_id"] = BUILD_MACHINE_ID
        path.write_text(json.dumps(runs, indent=2) + "\n")
        # Calkit staged the record as it wrote it
        run(["git", "add", ".calkit/stage-runs.json"], self.dest)

    def head(self) -> str:
        return run(["git", "rev-parse", "HEAD"], self.dest).strip()

    def results(self, table: str, education: bool) -> dict:
        return fit_table(self.dest / table, education)

    # Messy arms

    def build_messy(self) -> None:
        d = self.dest
        git = self.git

        def start() -> None:
            d.mkdir(parents=True)
            if git:
                run(["git", "init", "-q", "-b", "main"], d)
                self.write(".gitignore", "__pycache__/\n.ipynb_checkpoints/\n")
            self.copy(
                self.data / "participants.csv", "data/raw/participants.csv"
            )
            self.copy(self.data / "sessions_v1.csv", SESSIONS_V1)
            self.copy(SHARED / "codebook_v1.md", "codebook.md")
            self.copy(HIST / "README_messy.md", "README.md")
            self.copy(HIST / "requirements_messy.txt", "requirements.txt")

        def first_analysis() -> None:
            self.write("utils.py", get_utils(80))
            self.write(
                "prepare_data.py",
                get_flat_prepare(SESSIONS_V1, "data/merged.csv"),
            )
            run([PY, "prepare_data.py"], d)
            (d / "figures").mkdir(exist_ok=True)
            nb = make_notebook(
                get_analysis_cells(
                    "data/merged.csv", False, "figures/fig1.png", False
                )
            )
            write_notebook(execute(nb, d), d / "analysis.ipynb")
            if git:
                self.commit("initial commit")

        def first_draft() -> None:
            r = self.results("data/merged.csv", False)
            self.write(
                "paper/draft.md",
                format_report(
                    get_report_template(80, False, False),
                    r["ancova"],
                    r["change"],
                    "../figures/fig1.png",
                ),
            )
            if git:
                self.commit("first draft")

        def education() -> None:
            if not git:
                shutil.copy2(
                    d / "paper/draft.md", d / "paper/draft_2026-03-09.md"
                )
                self.keep_mtime.add("paper/draft_2026-03-09.md")
            cells = get_analysis_cells(
                "data/merged.csv", True, "figures/fig1_FINAL.png", True
            )
            before = get_analysis_cells(
                "data/merged.csv", False, "figures/fig1_FINAL.png", True
            )
            # Run once before education was added, then only the ANCOVA
            # cell and the figure again after, so the change-score cell's
            # output is from the model without education
            ran_before = execute(make_notebook(before), d)
            nb = execute(make_notebook(cells), d)
            nb.cells[6].outputs = ran_before.cells[6].outputs
            set_counts(nb, [1, 2, 3, 4, 9, 6, 7, 8, 10])
            write_notebook(nb, d / "analysis_v2.ipynb")
            s = self.results("data/merged.csv", True)
            stale_change = self.results("data/merged.csv", False)["change"]
            self.write(
                "paper/draft.md",
                format_report(
                    get_report_template(80, True, False),
                    s["ancova"],
                    stale_change,
                    "../figures/fig1_FINAL.png",
                ),
            )
            if git:
                self.commit("add education, new figure")

        def submit() -> None:
            shutil.copyfile(
                d / "paper/draft.md", d / "paper/draft_submitted.md"
            )
            if git:
                self.commit("submitted version")

        def corrected_export() -> None:
            self.copy(self.data / "sessions_v2.csv", SESSIONS_V2)
            self.copy(SHARED / "codebook.md", "codebook.md")
            if not git:
                shutil.copy2(d / "prepare_data.py", d / "prepare_data_old.py")
                self.keep_mtime.add("prepare_data_old.py")
            self.write(
                "prepare_data.py",
                get_flat_prepare(SESSIONS_V2, "data/merged_final.csv"),
            )
            run([PY, "prepare_data.py"], d)
            self.copy(HIST / "fit_model_flat.py", "fit_model.py")
            (d / "results").mkdir(exist_ok=True)
            run([PY, "-W", "ignore", "fit_model.py"], d)
            nb = execute(make_notebook(get_final_cells(ci=False)), d)
            write_notebook(nb, d / "analysis_v2_final.ipynb")
            self.write("paper/draft.md", self.typed_draft(80, ci=False))
            if git:
                self.commit("new data from coordinator")

        def reviewer_edits() -> None:
            self.write("utils.py", get_utils(85))
            nb = nbformat.read(d / "analysis_v2_final.ipynb", 4)
            fresh = make_notebook(get_final_cells(ci=True))
            nb.cells[4].source = fresh.cells[4].source
            write_notebook(nb, d / "analysis_v2_final.ipynb")
            # Methods and caption edited, numbers not yet
            text = (d / "paper/draft.md").read_text()
            text = text.replace("aged 60–80", "aged 60–85").replace(
                "Error bars are standard errors.",
                "Error bars are 95% confidence intervals.",
            )
            self.write("paper/draft.md", text)
            if git and self.stale:
                self.commit("address reviewer comments")

        def rerun() -> None:
            run([PY, "prepare_data.py"], d)
            run([PY, "-W", "ignore", "fit_model.py"], d)
            ran_before = nbformat.read(d / "analysis_v2_final.ipynb", 4)
            nb = execute(make_notebook(get_final_cells(ci=True)), d)
            # The age-range cell wasn't rerun
            nb.cells[3].outputs = ran_before.cells[3].outputs
            set_counts(nb, [1, 4, 3, 5])
            write_notebook(nb, d / "analysis_v2_final.ipynb")
            self.write("paper/draft.md", self.typed_draft(85, ci=True))

        def response() -> None:
            self.copy(
                HIST / "response_to_reviewers.md",
                "paper/response_to_reviewers.md",
            )
            if git:
                self.commit("reviewer comments")

        def abstract() -> None:
            r = json.loads((d / "results/model_ancova.json").read_text())
            self.write("talks/GSA2026_abstract.md", format_abstract(r))
            if git:
                self.commit("GSA abstract")

        self.step("2026-03-02T09:00:00", start)
        self.step("2026-03-02T15:00:00", first_analysis)
        self.step("2026-03-09T16:00:00", first_draft)
        self.step("2026-03-16T14:00:00", education)
        self.step("2026-03-23T11:00:00", submit)
        self.step("2026-04-14T10:00:00", corrected_export)
        self.step("2026-05-04T10:00:00", reviewer_edits)
        if self.stale:
            return
        self.step("2026-05-04T15:00:00", rerun)
        self.step("2026-05-11T12:00:00", response)
        self.step("2026-05-18T17:00:00", abstract)

    def typed_draft(self, max_age: int, ci: bool) -> str:
        """The current draft, retyped from results/*.json."""
        d = self.dest
        ancova = json.loads((d / "results/model_ancova.json").read_text())
        change = json.loads((d / "results/model_change.json").read_text())
        return format_report(
            get_report_template(max_age, True, ci),
            ancova,
            change,
            "../figures/fig1_FINAL_revised.png",
        )

    # Careful arms

    def build_careful(self) -> None:
        d = self.dest
        calkit = self.arm == "calkit"

        def start() -> None:
            d.mkdir(parents=True)
            run(["git", "init", "-q", "-b", "main"], d)
            if calkit:
                self.calkit_run("init")
            (d / "data/raw").mkdir(parents=True)
            self.copy(
                self.data / "participants.csv", "data/raw/participants.csv"
            )
            self.copy(self.data / "sessions_v1.csv", "data/raw/sessions.csv")
            self.copy(SHARED / "codebook_v1.md", "codebook.md")
            if calkit:
                self.calkit_run("add", "data/raw")
            self.commit("Add raw participant and session data with codebook")

        def scripts() -> None:
            self.write("scripts/utils.py", get_utils(80))
            self.copy(HIST / "prepare_data.py", "scripts/prepare_data.py")
            self.copy(HIST / "fit_model_v1.py", "scripts/fit_model.py")
            self.copy(HIST / "make_figure_se.py", "scripts/make_figure.py")
            self.copy(HIST / "write_report_v1.py", "scripts/write_report.py")
            self.write(
                "report_template.md", get_report_template(80, False, False)
            )
            self.commit("Add analysis scripts and report template")

        def runner() -> None:
            if calkit:
                self.add_calkit_pipeline()
            else:
                self.copy(HERE / "make/Makefile", "Makefile")
                self.copy(HIST / "README_make.md", "README.md")
                self.write("requirements.txt", "\n".join(PACKAGES) + "\n")
                self.write(".gitignore", "__pycache__/\n.venv/\n")
                self.commit("Add Makefile to run the analysis")

        def rerun(message: str = "Run analysis") -> None:
            if calkit:
                self.calkit_run("run")
                self.date_stage_runs()
                self.calkit_run("commit", "-m", "Run pipeline")
            else:
                run(["make", "-s", f"PYTHON={PY}"], d)
                self.commit(message)

        def explore() -> None:
            (d / "notebooks").mkdir(exist_ok=True)
            nb = execute(make_notebook(get_explore_cells()), d / "notebooks")
            nb.cells[-1].outputs = []
            set_counts(nb, [1, 4, 3, 2, None])
            write_notebook(nb, d / "notebooks/explore.ipynb")
            self.commit("Add exploratory notebook")

        def education() -> None:
            self.copy(SHARED / "fit_model.py", "scripts/fit_model.py")
            self.copy(SHARED / "write_report.py", "scripts/write_report.py")
            self.write(
                "report_template.md", get_report_template(80, True, False)
            )
            self.commit("Adjust models for education, as co-authors suggested")

        def answers() -> None:
            run([PY, str(HERE / "calkit/add_answers.py"), "calkit.yaml"], d)
            self.calkit_run("check", "questions")
            self.commit("Answer questions with pipeline evidence")

        def submit() -> None:
            self.tag("submitted", "Manuscript as submitted to the journal")

        def corrected_export() -> None:
            self.copy(self.data / "sessions_v2.csv", "data/raw/sessions.csv")
            self.copy(SHARED / "codebook.md", "codebook.md")
            if calkit:
                self.calkit_run("add", "data/raw/sessions.csv", "codebook.md")
            self.commit(
                "Use corrected sessions export with week-12 form B rescored"
            )

        def widen_ages() -> None:
            self.write("scripts/utils.py", get_utils(85))
            self.write(
                "report_template.md", get_report_template(85, True, False)
            )
            self.commit(
                "Widen eligible ages to 60–85, as the protocol says"
                " (reviewer 2.1)"
            )

        def ci_bars() -> None:
            self.copy(SHARED / "make_figure.py", "scripts/make_figure.py")
            self.write(
                "report_template.md", get_report_template(85, True, True)
            )
            self.commit("Show 95% CIs in Figure 1 (reviewer 1.2)")

        def response() -> None:
            self.copy(
                HIST / "response_to_reviewers.md",
                "paper/response_to_reviewers.md",
            )
            self.commit("Add response to reviewers")

        def abstract() -> None:
            r = json.loads((d / "results/model-ancova.json").read_text())
            self.write("talks/GSA2026_abstract.md", format_abstract(r))
            self.commit("Draft GSA 2026 abstract")

        self.step("2026-03-02T09:00:00", start)
        self.step("2026-03-02T10:00:00", scripts)
        self.step("2026-03-02T10:30:00", runner)
        self.step("2026-03-02T15:00:00", rerun)
        self.step("2026-03-04T16:00:00", explore)
        self.step("2026-03-16T13:00:00", education)
        self.step("2026-03-16T14:00:00", rerun)
        if calkit:
            self.step("2026-03-16T14:30:00", answers)
        self.step("2026-03-23T11:00:00", submit)
        self.step("2026-04-14T10:00:00", corrected_export)
        self.step("2026-04-14T11:00:00", rerun)
        self.step("2026-05-04T10:00:00", widen_ages)
        self.step("2026-05-04T10:30:00", ci_bars)
        if self.stale:
            return
        self.step("2026-05-04T15:00:00", rerun)
        self.step("2026-05-11T12:00:00", response)
        self.step("2026-05-18T17:00:00", abstract)

    def add_calkit_pipeline(self) -> None:
        d = self.dest
        # uv keeps an existing lock's versions, so the environment's
        # transitive dependencies are the same in every build
        self.copy(HERE / "calkit/uv.lock", "uv.lock")
        self.calkit_run(
            "new", "uv-env", "-n", "main", "--python", "3.12", *PACKAGES
        )
        common = ["-e", "main", "--no-check", "--no-commit"]
        self.calkit_run(
            "new",
            "python-script-stage",
            "-n",
            "prepare-data",
            *common,
            "-s",
            "scripts/prepare_data.py",
            "--arg=--participants",
            "--arg=data/raw/participants.csv",
            "--arg=--sessions",
            "--arg=data/raw/sessions.csv",
            "--arg=--out",
            "--arg=data/analysis.csv",
            "-i",
            "data/raw/participants.csv",
            "-i",
            "data/raw/sessions.csv",
            "-i",
            "scripts/utils.py",
            "-o",
            "data/analysis.csv",
        )
        self.calkit_run(
            "new",
            "python-script-stage",
            "-n",
            "fit-model",
            *common,
            "-s",
            "scripts/fit_model.py",
            "--arg=--data",
            "--arg=data/analysis.csv",
            "--arg=--adjustment",
            "--arg={adjustment}",
            "--arg=--out",
            "--arg=results/model-{adjustment}.json",
            "--iter",
            "adjustment",
            "ancova,change",
            "-i",
            "data/analysis.csv",
            "--out-git",
            "results/model-{adjustment}.json",
        )
        self.calkit_run(
            "new",
            "python-script-stage",
            "-n",
            "make-figure",
            *common,
            "-s",
            "scripts/make_figure.py",
            "--arg=--data",
            "--arg=data/analysis.csv",
            "--arg=--out",
            "--arg=results/score_by_week.png",
            "-i",
            "data/analysis.csv",
            "--out-git",
            "results/score_by_week.png",
        )
        self.calkit_run(
            "new",
            "python-script-stage",
            "-n",
            "write-report",
            *common,
            "-s",
            "scripts/write_report.py",
            "--arg=--primary",
            "--arg=results/model-ancova.json",
            "--arg=--sensitivity",
            "--arg=results/model-change.json",
            "--arg=--template",
            "--arg=report_template.md",
            "--arg=--figure",
            "--arg=score_by_week.png",
            "--arg=--out",
            "--arg=results/report.md",
            "-i",
            "results/model-ancova.json",
            "-i",
            "results/model-change.json",
            "-i",
            "report_template.md",
            "-i",
            "results/score_by_week.png",
            "--out-git",
            "results/report.md",
        )
        # Questions the analysis answers, declared up front
        questions = [
            (
                "Does computerized cognitive training raise cognitive scores"
                " in older adults?",
                "Training raises week-12 cognitive scores relative to"
                " waitlist control.",
                "ANCOVA: OLS of week-12 score on arm, baseline score, age per"
                " 10 years, and education (secondary as reference), in"
                " participants with a scored baseline and week-12"
                " assessment.",
            ),
            (
                "Is the training effect robust to analyzing change from"
                " baseline instead?",
                "The change-score estimate is close to the ANCOVA estimate.",
                "OLS of change in score from baseline to week 12 on arm,"
                " age, and education.",
            ),
            (
                "How do week-12 scores differ by education and age?",
                "Participants with more education gain more by week 12, and"
                " older participants gain less.",
                "Education and age coefficients of the ANCOVA model, with"
                " secondary education as the reference category.",
            ),
        ]
        for i, (q, hypothesis, approach) in enumerate(questions, 1):
            self.calkit_run("new", "question", q)
            self.calkit_run(
                "update",
                "question",
                str(i),
                "--hypothesis",
                hypothesis,
                "--approach",
                approach,
            )
        self.copy(HIST / "README_calkit.md", "README.md")
        self.commit("Add pipeline")
        assert (d / "calkit.yaml").exists()

    def build(self) -> None:
        if self.dest.exists():
            shutil.rmtree(self.dest)
        if self.arm.startswith("messy"):
            self.build_messy()
        else:
            self.build_careful()
        for p in self.dest.rglob("__pycache__"):
            shutil.rmtree(p)
        if self.git:
            status = run(["git", "status", "--porcelain"], self.dest)
            assert not status.strip(), status
            # Git's index records each file's inode and times; rebuild it
            # from HEAD without them, so it's the same in every build
            run(["git", "read-tree", "HEAD"], self.dest)
            # Blobs staged and replaced, e.g., Calkit's undated run record
            run(["git", "prune", "--expire=now"], self.dest)
            identities = run(
                ["git", "log", "--all", "--format=%an <%ae>%n%cn <%ce>"],
                self.dest,
            )
            builder = "{} <{}>".format(*arms.BUILDER)
            assert set(identities.split("\n")) - {""} == {builder}, identities


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "arm", choices=["messy", "messy-git", "make", "calkit"]
    )
    parser.add_argument("dest", type=Path)
    parser.add_argument("--stale", action="store_true")
    parser.add_argument("--calkit", default=arms.get_calkit_command())
    args = parser.parse_args()
    History(args.arm, args.dest.resolve(), args.stale, args.calkit).build()
    print(args.dest)


if __name__ == "__main__":
    main()
