"""Tests for ``calkit.models.pipeline``."""

import pytest
from pydantic import ValidationError

from calkit.models.pipeline import (
    JuliaCommandStage,
    JupyterNotebookStage,
    LatexStage,
    MatlabCommandStage,
    PythonScriptStage,
    SBatchStage,
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
    assert " -silent " in s.dvc_cmd
    s.verbose = True
    assert " -silent " not in s.dvc_cmd
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
        'calkit xenv -n j1 --no-check -- "println(\\"sup\\")"'
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
    assert sd["cmd"] == 'matlab -batch "disp(\\"Hello, MATLAB!\\");"'


def test_sbatchstage():
    s = SBatchStage(
        name="job1",
        script_path="scripts/run_job.sh",
        environment="slurm-env",
        args=["something", "else"],
        sbatch_options=["--time=01:00:00", "--mem=4G"],
        inputs=["data/input.txt"],
        outputs=["data/output.txt"],
    )
    sd = s.to_dvc()
    print(sd)
    assert sd["cmd"] == (
        "calkit slurm batch --name job1 --environment slurm-env "
        "--dep data/input.txt --out data/output.txt "
        "-s --time=01:00:00 -s --mem=4G -- scripts/run_job.sh something else"
    )
    assert "scripts/run_job.sh" in sd["deps"]
    assert "data/input.txt" in sd["deps"]
    out = {"data/output.txt": {"persist": True}}
    assert out in sd["outs"]
