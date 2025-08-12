"""Tests for ``calkit.models.pipeline``."""

import pytest
from pydantic import ValidationError

from calkit.models.pipeline import (
    JupyterNotebookStage,
    LatexStage,
    PythonScriptStage,
    StageIteration,
    WordToPdfStage,
)


def test_pythonscriptstage():
    s = PythonScriptStage.model_validate(
        dict(
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
        word_doc_path="my word doc.docx",
    )
    sd = s.to_dvc()
    assert sd["cmd"] == (
        'calkit office word-to-pdf "my word doc.docx" -o "my word doc.pdf"'
    )


def test_latexstage():
    s = LatexStage(environment="tex", target_path="my-paper.tex")
    assert " -silent " in s.dvc_cmd
    s.verbose = True
    assert " -silent " not in s.dvc_cmd
    assert "my-paper.tex" in s.dvc_deps
    assert "my-paper.pdf" in s.dvc_outs


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
    assert " -p param1=value1 " in dvc_stage["cmd"]
    assert " -p param2=value2 " in dvc_stage["cmd"]


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
