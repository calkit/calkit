"""Tests for ``calkit.models.pipeline``."""

import pytest
from pydantic import ValidationError

from calkit.models.io import PathOutput
from calkit.models.pipeline import (
    JsonToLatexStage,
    JuliaCommandStage,
    JuliaScriptStage,
    JupyterNotebookStage,
    LatexStage,
    MapPathsStage,
    MarimoHtmlWasmStage,
    MatlabCommandStage,
    MatlabScriptStage,
    Pipeline,
    PythonScriptStage,
    QuartoStage,
    StageIteration,
    WordToPdfStage,
)


def test_pythonscriptstage():
    s = PythonScriptStage.model_validate(
        dict(
            name="something",
            kind="python-script",
            script_path="scripts/my-script.py",
            environment="py1",
            inputs=["data/raw.csv"],
            outputs=[
                "data/processed.csv",
                dict(path="data/something.csv", storage="git"),
            ],
        )
    )
    sd = s.to_dvc()
    assert sd["cmd"] == (
        "calkit xenv -n py1 --no-check -- python scripts/my-script.py"
    )
    assert "scripts/my-script.py" in sd["deps"]
    s.always_run = True
    sd = s.to_dvc()
    assert sd["always_changed"]
    assert sd["outs"][0] == "data/processed.csv"
    assert sd["outs"][1] == {
        "data/something.csv": dict(cache=False, persist=False)
    }


def test_wordtopdfstage():
    s = WordToPdfStage(
        name="none",
        word_doc_path="my word doc.docx",
    )
    sd = s.to_dvc()
    assert sd["cmd"] == (
        'calkit office word-to-pdf "my word doc.docx" -o "my word doc.pdf"'
    )


def test_latexstage():
    s = LatexStage(
        name="something", environment="tex", target_path="my-paper.tex"
    )
    assert s.dvc_cmd.startswith("calkit latex build")
    assert " -e tex " in s.dvc_cmd
    assert " --verbose " not in s.dvc_cmd
    s.verbose = True
    assert " --verbose " in s.dvc_cmd
    assert "my-paper.tex" in s.dvc_deps
    assert "my-paper.pdf" in s.dvc_outs
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="my-paper.tex",
        latexmkrc_path="test/latexmkrc",
    )
    assert "test/latexmkrc" in s.dvc_deps
    assert "-r test/latexmkrc" in s.dvc_cmd
    # Test with pdf_storage set to "git"
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="my-paper.tex",
        pdf_storage="git",
    )
    assert s.dvc_outs == [{"my-paper.pdf": {"cache": False}}]
    # Test we don't change the user's preference if they put the PDF as an
    # output
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="my-paper.tex",
        pdf_storage="git",
        outputs=["my-paper.pdf"],
    )
    assert s.dvc_outs == ["my-paper.pdf"]
    # With no output_dir, the PDF sits next to the source
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="paper/my-paper.tex",
    )
    assert s.pdf_path == "paper/my-paper.pdf"
    assert "paper/my-paper.pdf" in s.dvc_outs
    # output_dir is relative to the project root (like every other Calkit path
    # field), so the PDF lands in <output_dir>/<stem>.pdf
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="paper/my-paper.tex",
        output_dir="paper/build",
    )
    assert s.pdf_path == "paper/build/my-paper.pdf"
    assert "paper/build/my-paper.pdf" in s.dvc_outs
    # The source path's .pdf is not assumed when output_dir is set
    assert "paper/my-paper.pdf" not in s.dvc_outs
    # output_dir is respected for git-stored PDFs too
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="paper/my-paper.tex",
        output_dir="paper/build",
        pdf_storage="git",
    )
    assert s.dvc_outs == [{"paper/build/my-paper.pdf": {"cache": False}}]
    # A trailing-slash / redundant "." segment normalizes cleanly
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="my-paper.tex",
        output_dir="./build/",
    )
    assert s.pdf_path == "build/my-paper.pdf"
    # Without a latexmkrc, output_dir/aux_dir drive latexmk via the build CLI
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="paper/my-paper.tex",
        output_dir="paper/build",
        aux_dir="paper/aux",
    )
    assert "--output-dir paper/build" in s.dvc_cmd
    assert "--aux-dir paper/aux" in s.dvc_cmd
    # With a latexmkrc, it stays authoritative -- Calkit does not pass the dir
    # flags (a CLI -outdir would override the rc's $out_dir)
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="paper/my-paper.tex",
        output_dir="paper/build",
        aux_dir="paper/aux",
        latexmkrc_path="paper/.latexmkrc",
    )
    assert "--output-dir" not in s.dvc_cmd
    assert "--aux-dir" not in s.dvc_cmd
    assert "-r paper/.latexmkrc" in s.dvc_cmd
    # Extra latexmk_args are passed straight through to latexmk
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="my-paper.tex",
        latexmk_args=["-pdflua", "-shell-escape"],
    )
    assert "--latexmk-arg -pdflua" in s.dvc_cmd
    assert "--latexmk-arg -shell-escape" in s.dvc_cmd
    # A latexmk_args entry that sets a Calkit-managed directory is a conflict
    with pytest.raises(ValidationError):
        LatexStage(
            name="something",
            environment="tex",
            target_path="my-paper.tex",
            output_dir="build",
            latexmk_args=["-outdir=other"],
        )
    # The same flag is allowed when the field is unset (escape hatch)
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="my-paper.tex",
        latexmk_args=["-outdir=other"],
    )
    assert "--latexmk-arg -outdir=other" in s.dvc_cmd
    # Paths/args with spaces are shell-quoted in the compiled command
    s = LatexStage(
        name="something",
        environment="tex",
        target_path="my paper.tex",
    )
    assert "'my paper.tex'" in s.dvc_cmd


def test_quartostage():
    s = QuartoStage(
        name="render-report",
        environment="analysis",
        target_path="report/report.qmd",
        inputs=["report/results.json", "figures"],
        outputs=["report/report.html"],
    )
    sd = s.to_dvc()
    assert sd["cmd"] == (
        "calkit xenv -n analysis --no-check -- quarto render report/report.qmd"
    )
    assert "report/report.qmd" in sd["deps"]
    assert "report/results.json" in sd["deps"]
    assert "figures" in sd["deps"]
    # Plain string outputs are DVC-cached by default
    assert "report/report.html" in sd["outs"]
    # The format and extra args are passed through to the CLI
    s = QuartoStage(
        name="render-report",
        environment="analysis",
        target_path="report/report.qmd",
        to="pdf",
        args=["--no-clean"],
        # A PathOutput can be used to store with Git instead
        outputs=[PathOutput(path="report/report.pdf", storage="git")],
    )
    assert s.dvc_cmd.endswith(
        "quarto render report/report.qmd --to pdf --no-clean"
    )
    assert s.dvc_outs == [
        {"report/report.pdf": {"cache": False, "persist": False}}
    ]
    # System environment renders without an xenv wrapper
    s = QuartoStage(
        name="render-report",
        environment="_system",
        target_path="report/report.qmd",
        outputs=["report/report.html"],
    )
    assert s.dvc_cmd == "quarto render report/report.qmd"


def test_jupyternotebookstage():
    def dvc_outs_to_str_list(dvc_stage) -> list[str]:
        outs = []
        for out in dvc_stage["outs"]:
            if isinstance(out, dict):
                outs.append(list(out.keys())[0])
            else:
                outs.append(out)
        return outs

    s = JupyterNotebookStage(
        name="whatever",
        environment="main",
        notebook_path="something.ipynb",
        inputs=["file.txt"],
        html_storage="git",
    )
    dvc_stage = s.to_dvc()
    outs = dvc_outs_to_str_list(dvc_stage)
    assert s.html_path in outs
    assert s.executed_notebook_path in outs
    assert "html" in dvc_stage["cmd"]
    assert "file.txt" in dvc_stage["deps"]
    s = JupyterNotebookStage(
        name="notebook1",
        environment="main",
        notebook_path="something.ipynb",
        inputs=["file.txt"],
        html_storage=None,
    )
    dvc_stage = s.to_dvc()
    outs = dvc_outs_to_str_list(dvc_stage)
    assert s.html_path not in outs
    assert s.executed_notebook_path in outs
    assert "html" not in dvc_stage["cmd"]
    # Test with parameters
    s = JupyterNotebookStage(
        name="notebook2",
        environment="main",
        notebook_path="something.ipynb",
        inputs=["file.txt"],
        html_storage=None,
        parameters={"param1": "value1", "param2": "value2"},
    )
    dvc_stage = s.to_dvc()
    outs = dvc_outs_to_str_list(dvc_stage)
    assert s.html_path not in outs
    assert s.executed_notebook_path in outs
    assert "html" not in dvc_stage["cmd"]
    assert (
        " --params-base64 "
        '"eyJwYXJhbTEiOiAidmFsdWUxIiwgInBhcmFtMiI6ICJ2YWx1ZTIifQ==" '
    ) in dvc_stage["cmd"]


def test_stageiteration():
    StageIteration(
        arg_name="param1",
        values=[1, 2, 3],
    )
    with pytest.raises(ValidationError):
        StageIteration(arg_name=["param1", "param2"], values=[1, 2, 3])
    i = StageIteration(arg_name=["param1", "param2"], values=[[1, 2], [3, 4]])
    i.values
    exp_vals = i.expand_values(params={})
    assert exp_vals == [{"param1": 1, "param2": 2}, {"param1": 3, "param2": 4}]


def test_juliacommandstage():
    s = JuliaCommandStage(name="a", environment="j1", command='println("sup")')
    sd = s.to_dvc()
    print(sd)
    assert sd["cmd"] == (
        'calkit xenv -n j1 --no-check -- -e "println(\\"sup\\")"'
    )


def test_juliascriptstage():
    s = JuliaScriptStage(
        name="script1",
        environment="julia-env",
        script_path="scripts/my_script.jl",
        args=["arg1", "arg2"],
    )
    sd = s.to_dvc()
    print(sd)
    assert sd["cmd"] == (
        'calkit xenv -n julia-env --no-check -- "scripts/my_script.jl" arg1 arg2'
    )


def test_matlabcommandstage():
    s = MatlabCommandStage(
        name="b", environment="m1", command='disp("Hello, MATLAB!");'
    )
    sd = s.to_dvc()
    print(sd)
    assert sd["cmd"] == (
        'calkit xenv -n m1 --no-check -- "disp(\\"Hello, MATLAB!\\");"'
    )
    s = MatlabCommandStage(
        name="c", environment="_system", command='disp("Hello, MATLAB!");'
    )
    sd = s.to_dvc()
    print(sd)
    assert sd["cmd"] == (
        'matlab -noFigureWindows -batch "disp(\\"Hello, MATLAB!\\");"'
    )


def test_matlabscriptstage():
    s = MatlabScriptStage(
        name="a",
        kind="matlab-script",
        environment="_system",
        script_path="scripts/my_script.m",
        matlab_path="scripts",
    )
    sd = s.to_dvc()
    print(sd)
    assert sd["cmd"] == (
        "matlab -noFigureWindows -batch \"addpath(genpath('scripts')); "
        "run('scripts/my_script.m');\""
    )
    with pytest.raises(ValidationError):
        s = MatlabScriptStage(
            name="b",
            kind="matlab-script",
            environment="_system",
            script_path="scripts/my_script.m",
            matlab_path="/some/abs/path",
        )
    # Ensure we can't use a relative path outside the project folder
    with pytest.raises(ValidationError):
        s = MatlabScriptStage(
            name="b",
            kind="matlab-script",
            environment="_system",
            script_path="scripts/my_script.m",
            matlab_path="../up/a/dir",
        )


def test_sbatchstage():
    """Cover ``SBatchStage`` model behavior and conversion to shell-script.

    Scenarios:
    - parsing an sbatch stage and converting via convert_sbatch_stages(),
    - the converted stage emits ``calkit scheduler batch``,
    - sbatch_options land in scheduler.options,
    - stage-level setup commands survive the conversion,
    - non-default env_default_* modes survive the conversion.
    """
    from calkit.models.pipeline import Pipeline, ShellScriptStage

    # Build a minimal Pipeline with one sbatch stage and convert it.
    pipeline = Pipeline.model_validate(
        {
            "stages": {
                "job1": {
                    "kind": "sbatch",
                    "script_path": "scripts/run_job.sh",
                    "environment": "slurm-env",
                    "args": ["something", "else"],
                    "sbatch_options": ["--time=01:00:00", "--mem=4G"],
                    "inputs": ["data/input.txt"],
                    "outputs": ["data/output.txt"],
                }
            }
        }
    )
    converted = pipeline.convert_sbatch_stages()
    assert "job1" in converted
    stage = pipeline.stages["job1"]
    assert isinstance(stage, ShellScriptStage)
    assert stage.scheduler is not None
    assert stage.scheduler.options == ["--time=01:00:00", "--mem=4G"]
    # Set the CLI alias as compilation would (default is already "scheduler").
    sd = stage.to_dvc()
    print(sd)
    assert sd["cmd"] == (
        "calkit scheduler batch --name job1 "
        "--environment slurm-env "
        "--dep data/input.txt --out data/output.txt "
        "--option --time=01:00:00 --option --mem=4G "
        "-- scripts/run_job.sh something else"
    )
    assert "--env-default-options" not in sd["cmd"]
    assert "--env-default-setup" not in sd["cmd"]
    assert "scripts/run_job.sh" in sd["deps"]
    assert "data/input.txt" in sd["deps"]
    # Stage-level setup commands survive conversion.
    pipeline2 = Pipeline.model_validate(
        {
            "stages": {
                "job-setup": {
                    "kind": "sbatch",
                    "script_path": "scripts/run_job.sh",
                    "environment": "slurm-env",
                    "scheduler": {
                        "setup": ["module purge", "module load python/3.11"],
                    },
                }
            }
        }
    )
    pipeline2.convert_sbatch_stages()
    sd2 = pipeline2.stages["job-setup"].to_dvc()
    assert "--setup 'module purge'" in sd2["cmd"]
    assert "--setup 'module load python/3.11'" in sd2["cmd"]
    # Non-default env_default_* modes survive.
    pipeline3 = Pipeline.model_validate(
        {
            "stages": {
                "job-opts": {
                    "kind": "sbatch",
                    "script_path": "scripts/run_job.sh",
                    "environment": "slurm-env",
                    "scheduler": {"env_default_options": "merge"},
                },
                "job-setup-ignore": {
                    "kind": "sbatch",
                    "script_path": "scripts/run_job.sh",
                    "environment": "slurm-env",
                    "scheduler": {"env_default_setup": "ignore"},
                },
            }
        }
    )
    pipeline3.convert_sbatch_stages()
    sd_opts = pipeline3.stages["job-opts"].to_dvc()
    assert "--env-default-options merge" in sd_opts["cmd"]
    assert "--env-default-setup" not in sd_opts["cmd"]
    sd_setup = pipeline3.stages["job-setup-ignore"].to_dvc()
    assert "--env-default-options" not in sd_setup["cmd"]
    assert "--env-default-setup ignore" in sd_setup["cmd"]


def test_mappathsstage():
    s = MapPathsStage(
        name="map1",
        paths=[
            dict(
                kind="file-to-file",
                src="data/input.txt",
                dest="data/output.txt",
            ),  # type: ignore
        ],
    )
    sd = s.to_dvc()
    print(sd)
    assert sd["cmd"] == (
        "calkit map-paths --file-to-file 'data/input.txt->data/output.txt'"
    )
    assert "data/input.txt" in sd["deps"]
    assert {"data/output.txt": {"cache": False, "persist": True}} in sd["outs"]


def test_jsontolatexstage():
    s = JsonToLatexStage(
        name="json2latex",
        inputs=["data/results.json", "more.json"],
        outputs=["paper/results.tex", "paper/results2.tex"],
        command_name="theresults",
        format={"result1": "{value1:.2f}", "result2": "{value2}"},
    )
    sd = s.to_dvc()
    print(sd)
    assert sd["cmd"] == (
        "calkit latex from-json 'data/results.json' 'more.json' "
        "--output 'paper/results.tex' --output 'paper/results2.tex' "
        "--command theresults --format-json "
        '\'{"result1": "{value1:.2f}", "result2": "{value2}"}\''
    )
    dvc_outs = s.dvc_outs
    assert {
        "paper/results.tex": {"cache": False, "persist": False}
    } in dvc_outs


def test_to_ck_dict() -> None:
    # Fields left at their defaults should not be serialized, so calkit.yaml
    # stays free of null and empty entries
    s = LatexStage(
        kind="latex",
        environment="tex",
        target_path="paper/paper.tex",
        outputs=["paper/paper.pdf"],
    )
    d = s.to_ck_dict()
    assert d == dict(
        kind="latex",
        environment="tex",
        target_path="paper/paper.tex",
        outputs=["paper/paper.pdf"],
    )
    # The kind discriminator is kept even though it has a default
    assert list(d)[0] == "kind"
    # Round-trip produces an equivalent stage
    assert LatexStage.model_validate(d) == s
    # Non-default values are kept, including in nested models
    s2 = PythonScriptStage(
        kind="python-script",
        environment="py",
        script_path="scripts/run.py",
        outputs=[PathOutput(path="out.csv", storage="git")],
        always_run=True,
    )
    d2 = s2.to_ck_dict()
    assert d2["always_run"] is True
    assert d2["outputs"] == [dict(path="out.csv", storage="git")]
    assert PythonScriptStage.model_validate(d2) == s2


def test_latex_stage_diffs():
    stage = LatexStage(
        name="paper-1",
        kind="latex",
        environment="tex",
        target_path="pubs/paper-1/main.tex",
        inputs=["figures/fig1.png"],
        diffs=[["v1", "v2"], "main"],
    )
    # A bare revision compares it against HEAD. Every comparison in a
    # pipeline is between two commits; one against the working tree can't
    # be reproduced, so it isn't the project's to keep.
    assert stage.diff_pairs == [("v1", "v2"), ("main", "HEAD")]
    # Building the document and comparing revisions of it have different
    # inputs, so they are separate DVC stages: adding a comparison
    # shouldn't rebuild the paper, and chaining them with && assumes a
    # shell not everyone has
    assert stage.dvc_cmd == (
        "calkit latex build -e tex --no-check pubs/paper-1/main.tex"
    )
    assert stage.dvc_outs == ["pubs/paper-1/main.pdf"]
    fake = {
        "v1": "aaa1111",
        "v2": "bbb2222",
        "main": "ccc3333",
        "HEAD": "ddd4",
    }
    extra = stage.extra_dvc_stages(resolve_ref=fake.get)
    assert list(extra) == ["paper-1-diff-v1-v2", "paper-1-diff-main"]
    # Revisions are resolved into the command, so DVC sees a moving end
    # move, while the output location keeps the pair as written
    assert extra["paper-1-diff-v1-v2"]["cmd"] == (
        "calkit latex diff -e tex --no-check --from aaa1111 --to bbb2222 "
        "--output-dir .calkit/latex-diffs/v1..v2 pubs/paper-1/main.tex"
    )
    # HEAD is what a comparison runs up to unless it says otherwise, so
    # naming it would only add noise
    assert extra["paper-1-diff-main"]["outs"] == [
        ".calkit/latex-diffs/main/pubs/paper-1/main.pdf"
    ]
    # The command names the exact commits, so nothing has to run
    # unconditionally. A comparison up to HEAD still depends on the
    # document's files, since a DVC-tracked figure's content isn't in Git
    # and only the dependency catches a change to it.
    assert not any("always_changed" in st for st in extra.values())
    assert extra["paper-1-diff-v1-v2"]["deps"] == []
    assert extra["paper-1-diff-main"]["deps"] == [
        "pubs/paper-1/main.tex",
        "figures/fig1.png",
    ]
    # Without a resolver the command holds a name rather than a commit, so
    # a moving end has nothing DVC could notice
    unresolved = stage.extra_dvc_stages()
    assert unresolved["paper-1-diff-main"]["always_changed"] is True
    assert "always_changed" not in unresolved["paper-1-diff-v1-v2"]
    # Storage is chosen for diffs the same way it is for the document
    git_stored = LatexStage(
        name="paper-1",
        kind="latex",
        environment="tex",
        target_path="pubs/paper-1/main.tex",
        diffs=[["v1", "v2"]],
        diff_pdf_storage="git",
    )
    assert git_stored.extra_dvc_stages()["paper-1-diff-v1-v2"]["outs"] == [
        {".calkit/latex-diffs/v1..v2/pubs/paper-1/main.pdf": {"cache": False}}
    ]
    for bad in [[["v1"]], [["v1", "v2", "v3"]], [["v1", ""]], [["v1", "v1"]]]:
        with pytest.raises(ValidationError):
            LatexStage(
                name="paper-1",
                kind="latex",
                environment="tex",
                target_path="pubs/paper-1/main.tex",
                diffs=bad,
            )


def test_marimohtmlwasmstage():
    s = MarimoHtmlWasmStage(
        name="build-app",
        environment="py",
        notebook_path="notebook.py",
        layout_path="layouts/notebook.grid.json",
        show_code=True,
        include_paths=[
            "processed/all-simulated.csv",
            "figures/naca0012-aoa-*-umag.png",
        ],
        output_dir="app",
    )
    sd = s.to_dvc()
    # We dispatch into the environment ourselves rather than wrapping in
    # xenv, since the assembly step runs outside it
    assert sd["cmd"] == (
        "calkit nb export-marimo-wasm --environment py --no-check --show-code "
        "--layout layouts/notebook.grid.json "
        "--include processed/all-simulated.csv "
        "--include 'figures/naca0012-aoa-*-umag.png' -o app notebook.py"
    )
    # The notebook and layout are deps, and a glob is reduced to its longest
    # non-glob parent so ordering holds before the files exist
    assert "notebook.py" in sd["deps"]
    assert "layouts/notebook.grid.json" in sd["deps"]
    assert "processed/all-simulated.csv" in sd["deps"]
    assert "figures" in sd["deps"]
    assert "figures/naca0012-aoa-*-umag.png" not in sd["deps"]
    # The app is DVC-cached by default, since it's far too big for Git
    assert sd["outs"] == [{"app": {"cache": True}}]
    assert s.app_outputs == [PathOutput(path="app", storage="dvc")]
    # Defaults stay off the command line
    s = MarimoHtmlWasmStage(
        name="build-app",
        environment="py",
        notebook_path="notebook.py",
        output_dir="app",
    )
    assert s.dvc_cmd == (
        "calkit nb export-marimo-wasm --environment py --no-check -o app notebook.py"
    )
    assert s.dvc_deps == ["notebook.py"]
    # Storage is selectable, since a tiny app may belong in Git
    s = MarimoHtmlWasmStage(
        name="build-app",
        environment="py",
        notebook_path="notebook.py",
        output_dir="app",
        output_storage="git",
    )
    assert s.dvc_outs == [{"app": {"cache": False}}]
    # An editable app always shows its code, so asking for both is a mistake
    with pytest.raises(ValidationError):
        MarimoHtmlWasmStage(
            name="build-app",
            environment="py",
            notebook_path="notebook.py",
            mode="edit",
            show_code=True,
            output_dir="app",
        )
    # Writing out a default explicitly asks for nothing we can't do, so it's
    # accepted; this is also what a round trip through model_dump produces
    s = MarimoHtmlWasmStage(
        name="build-app",
        environment="py",
        notebook_path="notebook.py",
        output_dir="app",
        mode="run",
        show_code=False,
    )
    assert MarimoHtmlWasmStage.model_validate(s.model_dump()).mode == "run"
    # Validation runs the notebook, doubling the stage's runtime, so it can
    # be turned off for one that's already executed elsewhere
    s = MarimoHtmlWasmStage(
        name="build-app",
        environment="py",
        notebook_path="notebook.py",
        output_dir="app",
        validate_notebook=False,
    )
    assert " --no-validate" in s.dvc_cmd


def test_mappathsstage_rejects_paths_outside_the_project():
    # A legitimate mapping is unaffected
    s = MapPathsStage(
        name="copy-figures",
        paths=[
            dict(kind="dir-to-dir-replace", src="figures", dest="paper/figs")
        ],
    )
    assert s.paths[0].src == "figures"
    # dir-to-dir-replace deletes its destination, and map-paths is the one
    # stage kind the hub runs itself, so a '../' escape would let a project
    # delete or read outside its own directory
    for bad in [
        dict(kind="dir-to-dir-replace", src="figures", dest="../../victim"),
        dict(kind="dir-to-dir-merge", src="../../secrets", dest="paper/figs"),
        dict(kind="file-to-file", src="/etc/passwd", dest="paper/leak.tex"),
        dict(kind="file-to-dir", src="results.tex", dest="/tmp/exfil"),
    ]:
        with pytest.raises(ValidationError):
            MapPathsStage(name="copy-figures", paths=[bad])


def test_stage_rejects_wdir_outside_the_project():
    # A subdirectory of the project is the point of the field
    s = PythonScriptStage(
        name="run",
        environment="py",
        script_path="run.py",
        wdir="sub",
    )
    assert s.wdir == "sub"
    assert s.to_dvc()["wdir"] == "sub"
    # Unset stays unset rather than defaulting to something
    assert (
        PythonScriptStage(
            name="run", environment="py", script_path="run.py"
        ).wdir
        is None
    )
    # wdir becomes the DVC stage's working directory and is joined with the
    # stage's other paths, so an absolute or escaping value would run the
    # pipeline outside the project
    for bad in ["/etc", "../..", "../sibling", "sub/../../.."]:
        with pytest.raises(ValidationError):
            PythonScriptStage(
                name="run",
                environment="py",
                script_path="run.py",
                wdir=bad,
            )


def test_stage_paths_reject_empty_and_project_root():
    # An empty or blank path is Path('.'), which would otherwise pass every
    # check and silently mean the project root
    for bad in ["", "   "]:
        with pytest.raises(ValidationError):
            PythonScriptStage(name="run", environment="py", script_path=bad)
        with pytest.raises(ValidationError):
            PythonScriptStage(
                name="run", environment="py", script_path="run.py", wdir=bad
            )
    # A path that walks back out and in again is collapsed, so it can't
    # reach a caller still spelled the way it was written
    s = PythonScriptStage(
        name="run",
        environment="py",
        script_path="sub/../run.py",
        wdir="sub/nested/..",
    )
    assert s.script_path == "run.py"
    assert s.wdir == "sub"
    # dir-to-dir-replace deletes its destination before copying, so the
    # project root is never a valid target, however it's spelled
    for bad in ["", ".", "sub/..", "a/../b/.."]:
        with pytest.raises(ValidationError):
            MapPathsStage(
                name="copy",
                paths=[dict(kind="dir-to-dir-replace", src="figs", dest=bad)],
            )
    # The other kinds only copy into their destination, so the project root
    # is a fine target for them
    s = MapPathsStage(
        name="copy",
        paths=[
            dict(kind="file-to-dir", src="sub/README.md", dest="."),
            dict(kind="dir-to-dir-merge", src="figs", dest="."),
        ],
    )
    assert [p.dest for p in s.paths] == [".", "."]


def test_object_inputs_survive_round_trips():
    # An output copied verbatim into another stage's inputs arrives as an
    # object. Its extra keys are kept, so rewriting a stage back to
    # calkit.yaml doesn't quietly drop them.
    stage = PythonScriptStage.model_validate(
        {
            "kind": "python-script",
            "environment": "main",
            "script_path": "s.py",
            "inputs": [{"path": "data.csv", "storage": "dvc"}],
        }
    )
    dumped = stage.inputs[0].model_dump()
    assert dumped == {"path": "data.csv", "storage": "dvc"}
    # Only the path is a dependency, wherever it happens to be stored
    assert stage.dvc_deps == ["s.py", "data.csv"]


def test_json_to_latex_cmd_uses_paths_not_objects():
    # The command interpolates input paths, so an object input has to be
    # unwrapped rather than rendered as its repr
    stage = JsonToLatexStage.model_validate(
        {
            "kind": "json-to-latex",
            "inputs": [
                "a.json",
                {"path": "b.json", "storage": "dvc"},
                {"from_stage_outputs": "compute"},
            ],
            "outputs": ["out.tex"],
        }
    )
    cmd = stage.dvc_cmd
    assert "'a.json'" in cmd
    assert "'b.json'" in cmd
    assert "PathInput" not in cmd
    assert "from_stage_outputs" not in cmd


def test_system_env_can_wrap_a_runtime():
    # A system env says which machine to run on, so it composes with an
    # inner runtime the same way a scheduler env does
    pipeline = Pipeline.model_validate(
        {
            "stages": {
                "sim": {
                    "kind": "python-script",
                    "environment": "cluster:py",
                    "script_path": "s.py",
                    "inputs": ["data/in.csv"],
                    "outputs": ["results/out.csv"],
                },
                "build": {
                    "kind": "shell-command",
                    "environment": "cluster",
                    "command": "make",
                    "outputs": ["build"],
                },
            }
        }
    )
    envs = {
        "cluster": {
            "kind": "system",
            "host": "box.example.org",
            "user": "me",
            "wdir": "/home/me/proj",
        },
        "py": {"kind": "uv", "path": "pyproject.toml"},
        "other": {"kind": "system", "host": "box2.example.org"},
    }
    pipeline.set_stage_scheduler_options(envs)
    # Dispatch to the machine first, then activate the runtime there. What
    # moves is derived from the stage, so it can't drift out of step with
    # the pipeline the way a hand-kept list of paths would.
    assert pipeline.stages["sim"].xenv_cmd == (
        "calkit xenv -n cluster --no-check "
        "--send s.py --send data/in.csv --get results/out.csv "
        "-- calkit xenv -n py --no-check --"
    )
    # On its own it just runs the stage on that machine
    assert pipeline.stages["build"].xenv_cmd == (
        "calkit xenv -n cluster --no-check --get build --"
    )
    # A stage that runs here says nothing about transfers
    local = Pipeline.model_validate(
        {
            "stages": {
                "here": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "s.py",
                    "outputs": ["out.csv"],
                }
            }
        }
    )
    local.set_stage_scheduler_options(envs)
    assert local.stages["here"].xenv_cmd == ("calkit xenv -n py --no-check --")
    # The inner env has to be a runtime: another machine or a scheduler
    # would mean two answers to where the stage runs
    for inner in ["other", "sched"]:
        bad = Pipeline.model_validate(
            {
                "stages": {
                    "sim": {
                        "kind": "python-script",
                        "environment": f"cluster:{inner}",
                        "script_path": "s.py",
                    }
                }
            }
        )
        with pytest.raises(ValueError, match="must be a runtime"):
            bad.set_stage_scheduler_options(
                envs | {"sched": {"kind": "slurm", "host": "hpc.edu"}}
            )
