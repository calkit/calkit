"""Tests for ``calkit.models.pipeline``."""

import pytest
from pydantic import ValidationError

from calkit.models.pipeline import (
    JsonToLatexStage,
    JuliaCommandStage,
    JuliaScriptStage,
    JupyterNotebookStage,
    LatexStage,
    MapPathsStage,
    MatlabCommandStage,
    MatlabScriptStage,
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
    assert sd["cmd"] == 'matlab -batch "disp(\\"Hello, MATLAB!\\");"'


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
    assert (
        sd["cmd"]
        == "matlab -batch \"addpath(genpath('scripts')); run('scripts/my_script.m');\""
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
    # Test with `iterate_over`
    s = SBatchStage(
        name="job2",
        script_path="scripts/run_job.sh",
        environment="slurm-env",
        args=["{input_file}"],
        iterate_over=[
            StageIteration(
                arg_name="input_file",
                values=["data/input1.txt", "data/input2.txt"],
            )
        ],
    )
    sd = s.to_dvc()
    assert s.log_output.path == ".calkit/slurm/logs/job2/{input_file}.log"
    print(sd)
    assert "--name job2@{input_file}" in sd["cmd"]


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
