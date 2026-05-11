"""Tests for ``calkit.pipeline``."""

import os
import subprocess

import git
import pytest

import calkit
import calkit.pipeline
from calkit.environments import get_env_lock_fpath
from calkit.pipeline import (
    _expand_dep_excluding_subprojects,
    collapse_dvc_stages,
    stages_are_similar,
)


def test_stages_are_similar():
    # Test identical Python script stages
    stage1 = {
        "kind": "python-script",
        "script_path": "process.py",
        "args": ["--verbose"],
    }
    stage2 = {
        "kind": "python-script",
        "script_path": "process.py",
        "args": ["--verbose"],
    }
    assert stages_are_similar(stage1, stage2)
    # Test different script paths
    stage3 = {
        "kind": "python-script",
        "script_path": "other.py",
        "args": ["--verbose"],
    }
    assert not stages_are_similar(stage1, stage3)
    # Test different args
    stage4 = {
        "kind": "python-script",
        "script_path": "process.py",
        "args": ["--quiet"],
    }
    assert not stages_are_similar(stage1, stage4)
    # Test different kinds
    stage5 = {"kind": "julia-script", "script_path": "process.py"}
    assert not stages_are_similar(stage1, stage5)
    # Test shell commands
    cmd1 = {"kind": "shell-command", "command": "echo 'Hello World'"}
    cmd2 = {"kind": "shell-command", "command": "echo 'Hello World'"}
    assert stages_are_similar(cmd1, cmd2)
    cmd3 = {"kind": "shell-command", "command": "echo 'Goodbye'"}
    assert not stages_are_similar(cmd1, cmd3)
    # Test notebook stages
    nb1 = {"kind": "jupyter-notebook", "notebook_path": "analysis.ipynb"}
    nb2 = {"kind": "jupyter-notebook", "notebook_path": "analysis.ipynb"}
    assert stages_are_similar(nb1, nb2)
    nb3 = {"kind": "jupyter-notebook", "notebook_path": "other.ipynb"}
    assert not stages_are_similar(nb1, nb3)
    # Test LaTeX stages
    tex1 = {"kind": "latex", "target_path": "paper.tex"}
    tex2 = {"kind": "latex", "target_path": "paper.tex"}
    assert stages_are_similar(tex1, tex2)
    tex3 = {"kind": "latex", "target_path": "thesis.tex"}
    assert not stages_are_similar(tex1, tex3)
    # Test MATLAB command
    mat1 = {"kind": "matlab-command", "command": "disp('hello')"}
    mat2 = {"kind": "matlab-command", "command": "disp('hello')"}
    assert stages_are_similar(mat1, mat2)
    mat3 = {"kind": "matlab-command", "command": "disp('goodbye')"}
    assert not stages_are_similar(mat1, mat3)
    # Test plain command stages
    command1 = {"kind": "command", "command": "-i figure.mmd -o figure.svg"}
    command2 = {"kind": "command", "command": "-i figure.mmd -o figure.svg"}
    assert stages_are_similar(command1, command2)
    command3 = {"kind": "command", "command": "-i other.mmd -o other.svg"}
    assert not stages_are_similar(command1, command3)


def test_to_dvc():
    # Test typical proper usage
    envs = {
        "py": {
            "kind": "venv",
            "path": "requirements.txt",
            "prefix": ".venv",
        },
        "something": {
            "kind": "conda",
            "path": "environment.yaml",
        },
    }
    ck_info = {
        "environments": envs,
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "something/my-cool-script.py",
                    "outputs": [
                        "my-output.out",
                        {
                            "path": "something/else.pickle",
                            "storage": "git",
                            "delete_before_run": False,
                        },
                    ],
                }
            }
        },
    }
    stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    stage = stages["get-data"]
    assert stage["outs"][0] == "my-output.out"
    env_lock = get_env_lock_fpath(
        env=ck_info["environments"]["py"],
        env_name="py",
        as_posix=True,
        for_dvc=True,
    )
    assert env_lock in stage["deps"]
    # TODO: Test other stage types
    # Test when user forgets to add an environment
    ck_info = {
        "environments": envs,
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "script_path": "something/my-cool-script.py",
                    "outputs": [
                        "my-output.out",
                    ],
                }
            }
        },
    }
    with pytest.raises(ValueError):
        calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    # Test that we can define inputs from stage outputs
    ck_info = {
        "environments": envs,
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "something",
                    "script_path": "something/my-cool-script.py",
                    "outputs": [
                        "my-output.out",
                    ],
                },
                "process-data": {
                    "kind": "python-script",
                    "script_path": "something.py",
                    "environment": "py",
                    "inputs": [
                        {"from_stage_outputs": "get-data"},
                        "something.else.txt",
                    ],
                },
            }
        },
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    print(dvc_stages)
    assert "my-output.out" in dvc_stages["process-data"]["deps"]
    assert "something.else.txt" in dvc_stages["process-data"]["deps"]
    # Test a complex pipeline with iterations and parameters
    ck_info = {
        "environments": envs,
        "parameters": {
            "param1": [{"range": {"start": 5, "stop": 23, "step": 2}}],
            "param2": ["s", "m", "l"],
            "param3": [
                {"range": {"start": 0.1, "stop": 1.1, "step": 0.11}},
                55,
                "something",
            ],
        },
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "something",
                    "script_path": "something/my-cool-script.py",
                    "args": ["{my_parameter}"],
                    "outputs": [
                        "my-output.out",
                    ],
                    "iterate_over": [
                        {"arg_name": "my_parameter", "values": [1, 2, 3.5]}
                    ],
                },
                "process-data": {
                    "kind": "python-script",
                    "script_path": "something.py",
                    "args": ["--something", "{param_a}"],
                    "environment": "py",
                    "inputs": ["my-input-{param_a}"],
                    "outputs": ["out-{param_a}.txt"],
                    "iterate_over": [
                        {
                            "arg_name": "param_a",
                            "values": [{"parameter": "param3"}],
                        }
                    ],
                },
            }
        },
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    matrix = dvc_stages["process-data"]["matrix"]
    assert matrix["param_a"][0] == 0.1
    assert 55 in matrix["param_a"]
    assert "something" in matrix["param_a"]
    outs = dvc_stages["process-data"]["outs"]
    assert outs[0] == "out-${item.param_a}.txt"
    print(dvc_stages)


def test_to_dvc_from_matrix_outs():
    # Test that we can define inputs from matrix stage outputs
    ck_info = {
        "environments": {
            "py": {
                "kind": "venv",
                "path": "requirements.txt",
                "prefix": ".venv",
            },
            "something": {
                "kind": "conda",
                "path": "environment.yaml",
            },
        },
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "something",
                    "script_path": "something/my-cool-script.py",
                    "iterate_over": [
                        {"arg_name": "var1", "values": [1, 2, 3]},
                        {"arg_name": "var2", "values": ["a", "b", "c"]},
                    ],
                    "outputs": [
                        "out-{var1}-{var2}.out",
                    ],
                },
                "process-data": {
                    "kind": "python-script",
                    "script_path": "something.py",
                    "environment": "py",
                    "inputs": [
                        {"from_stage_outputs": "get-data"},
                        "something.else.txt",
                    ],
                },
            }
        },
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    print(dvc_stages)
    for var1 in [1, 2, 3]:
        for var2 in ["a", "b", "c"]:
            assert (
                f"out-{var1}-{var2}.out" in dvc_stages["process-data"]["deps"]
            )
    assert "something.else.txt" in dvc_stages["process-data"]["deps"]


def test_to_dvc_notebook_stage():
    # Test we can create a notebook stage properly, which involves a cleaning
    # stage to use as a DVC dependency
    nb_path = "something/my-cool-notebook.ipynb"
    ck_info = {
        "environments": {
            "something": {
                "kind": "conda",
                "path": "environment.yaml",
            },
        },
        "pipeline": {
            "stages": {
                "notebook-1": {
                    "kind": "jupyter-notebook",
                    "environment": "something",
                    "notebook_path": nb_path,
                    "outputs": [
                        "figures/fig1.png",
                    ],
                    "html_storage": "dvc",
                    "cleaned_ipynb_storage": "git",
                    "executed_ipynb_storage": None,
                },
            }
        },
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    print(dvc_stages)
    stage = dvc_stages["notebook-1"]
    assert "--to html" in stage["cmd"]
    found_html = False
    for out in stage["outs"]:
        if not isinstance(out, dict):
            continue
        p = list(out.keys())[0]
        if p.endswith(".html"):
            found_html = True
            assert out[p]["cache"]
    assert found_html
    # Test we can use parameters and iterations in notebook stages
    ck_info = {
        "environments": {
            "something": {
                "kind": "conda",
                "path": "environment.yaml",
            },
        },
        "parameters": {
            "param1": [{"range": {"start": 5, "stop": 23, "step": 2}}],
            "param2": ["s", "m", "l"],
            "param3": [
                {"range": {"start": 0.1, "stop": 1.1, "step": 0.11}},
                55,
                "something",
            ],
        },
        "pipeline": {
            "stages": {
                "notebook-1": {
                    "kind": "jupyter-notebook",
                    "environment": "something",
                    "notebook_path": nb_path,
                    "outputs": [
                        "figures/fig1.png",
                    ],
                    "html_storage": "dvc",
                    "cleaned_ipynb_storage": "git",
                    "executed_ipynb_storage": None,
                    "parameters": {
                        "param1": "{param1}",
                        "param2": "{param2}",
                        "param3": "{param3}",
                    },
                    "iterate_over": [
                        {
                            "arg_name": "param1",
                            "values": [{"parameter": "param1"}],
                        },
                        {
                            "arg_name": "param2",
                            "values": [{"parameter": "param2"}],
                        },
                        {
                            "arg_name": "param3",
                            "values": [{"parameter": "param3"}],
                        },
                    ],
                },
            }
        },
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    print(dvc_stages)
    stage = dvc_stages["notebook-1"]
    assert stage["cmd"].startswith("calkit nb execute")
    assert "--params-base64" in stage["cmd"]
    assert stage["matrix"]["param1"][0] == 5.0
    assert "m" in stage["matrix"]["param2"]
    assert "something" in stage["matrix"]["param3"]


def test_to_dvc_list_of_list_iteration():
    # Test that we can define iteration over a list of lists
    ck_info = {
        "environments": {
            "something": {
                "kind": "conda",
                "path": "environment.yaml",
            },
            "py": {
                "kind": "venv",
                "path": "requirements.txt",
                "prefix": ".venv",
            },
        },
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "something",
                    "script_path": "something/my-cool-script.py",
                    "args": ["--a1={var1}", "--a2={var2}"],
                    "iterate_over": [
                        {
                            "arg_name": ["var1", "var2"],
                            "values": [[1, "a"], [2, "b"], [3, "c"]],
                        },
                    ],
                    "outputs": [
                        "out-{var1}-{var2}.out",
                        "out2-{var1}-{var2}.out",
                    ],
                },
                "process-data": {
                    "kind": "python-script",
                    "script_path": "something.py",
                    "environment": "py",
                    "inputs": [
                        {"from_stage_outputs": "get-data"},
                        "something.else.txt",
                    ],
                },
            }
        },
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    stage = dvc_stages["get-data"]
    assert "--a1=${item._arg0.var1} --a2=${item._arg0.var2}" in stage["cmd"]
    matrix = stage["matrix"]
    assert matrix == {
        "_arg0": [
            {"var1": 1, "var2": "a"},
            {"var1": 2, "var2": "b"},
            {"var1": 3, "var2": "c"},
        ]
    }
    assert stage["outs"] == [
        "out-${item._arg0.var1}-${item._arg0.var2}.out",
        "out2-${item._arg0.var1}-${item._arg0.var2}.out",
    ]
    print(dvc_stages)
    stage2 = dvc_stages["process-data"]
    assert "out-1-a.out" in stage2["deps"]
    assert "out2-2-b.out" in stage2["deps"]


def test_remove_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # Test that we can remove a stage from the pipeline
    ck_info = {
        "environments": {
            "py": {
                "kind": "venv",
                "path": "requirements.txt",
                "prefix": ".venv",
            }
        },
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "something/my-cool-script.py",
                    "outputs": [
                        "my-output.out",
                    ],
                },
                "process-data": {
                    "kind": "python-script",
                    "script_path": "something.py",
                    "environment": "py",
                    "inputs": ["my-input.txt"],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "check", "pipeline", "-c"])
    with open("dvc.yaml", "r") as f:
        dvc_yaml = calkit.ryaml.load(f)
    assert "get-data" in dvc_yaml["stages"]
    assert "process-data" in dvc_yaml["stages"]
    # Now remove the get-data stage
    ck_info["pipeline"]["stages"].pop("get-data")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "check", "pipeline", "-c"])
    with open("dvc.yaml", "r") as f:
        dvc_yaml = calkit.ryaml.load(f)
    assert "get-data" not in dvc_yaml["stages"]
    assert "process-data" in dvc_yaml["stages"]


def test_sbatch_stage_to_dvc(tmp_dir):
    """Cover the SLURM stage compilation paths.

    Scenarios in one test (per AGENTS.md guidance):
    - direct sbatch stage on a plain slurm env with options + outputs,
    - composite ``slurm-env:py1`` wrapping a python-script (default
      ``replace`` mode stays implicit),
    - composite ``slurm-env:r1`` wrapping an r-script,
    - composite ``slurm-env:py1`` wrapping a shell-command,
    - composite ``slurm-env:julia1`` wrapping a julia-script with
      stage-level setup and explicit ``env_default_*: ignore``,
    - composite ``slurm-env:julia1`` wrapping a jupyter-notebook,
    - env-level defaults are NOT baked into the compiled stage cmd
      (they are merged at submission by ``calkit slurm batch``),
    - the env lock file is added as a dep on every stage that touches the
      slurm env.
    """
    envs = {
        "slurm-env": {
            "kind": "slurm",
            "default_setup": ["module purge", "module load julia/1.11"],
            "default_options": ["--account=foo"],
        },
        "julia1": {
            "kind": "julia",
            "julia": "1.11",
            "path": "Project.toml",
        },
        "py1": {"kind": "uv", "path": "pyproject.toml"},
        "r1": {"kind": "renv", "path": "DESCRIPTION"},
    }
    pipeline = {
        "stages": {
            "job1": {
                "kind": "sbatch",
                "script_path": "scripts/run_job.sh",
                "environment": "slurm-env",
                "args": ["something", "else"],
                "sbatch_options": ["--time=01:00:00", "--mem=4G"],
                "inputs": ["data/input.txt"],
                "outputs": [
                    {
                        "path": "data/output.txt",
                        "storage": "git",
                        "delete_before_run": False,
                    },
                    "data/output2.txt",
                ],
            },
            # python-script in a composite slurm env; default mode means
            # no --env-default-* flags are emitted.
            "py-job": {
                "kind": "python-script",
                "script_path": "scripts/run.py",
                "environment": "slurm-env:py1",
                "args": ["--flag", "value"],
                "inputs": ["data/input_py.txt"],
                "outputs": ["data/output_py.txt"],
            },
            # r-script in a composite slurm env.
            "r-job": {
                "kind": "r-script",
                "script_path": "scripts/run.R",
                "environment": "slurm-env:r1",
                "outputs": ["data/output_r.txt"],
            },
            # shell-command in a composite slurm env.
            "sh-cmd": {
                "kind": "shell-command",
                "command": "echo hi",
                "environment": "slurm-env:py1",
            },
            # julia-script with stage-level setup + opt-out of env defaults.
            "job2": {
                "kind": "julia-script",
                "script_path": "something.jl",
                "environment": "slurm-env:julia1",
                "inputs": ["data/input2.txt"],
                "outputs": ["data/output3.txt"],
                "slurm": {
                    "setup": ["module load gcc/12"],
                    "env_default_options": "ignore",
                    "env_default_setup": "ignore",
                },
            },
            # Jupyter notebook in a composite slurm env.
            "notebook": {
                "kind": "jupyter-notebook",
                "notebook_path": "analysis.ipynb",
                "environment": "slurm-env:julia1",
                "html_storage": "dvc",
                "cleaned_ipynb_storage": None,
                "executed_ipynb_storage": "git",
                "inputs": ["data/input2.txt"],
                "outputs": ["data/notebook_output.txt"],
            },
        },
    }
    stages = calkit.pipeline.to_dvc(
        ck_info={
            "environments": envs,
            "pipeline": pipeline,
        },
        write=False,
    )
    slurm_lock = ".calkit/env-locks/slurm-env.json"
    stage = stages["job1"]
    print(stage)
    assert stage["cmd"] == (
        "calkit slurm batch --name job1 "
        "--environment slurm-env "
        f"--dep data/input.txt --dep {slurm_lock} "
        "--out data/output2.txt "
        "-s --time=01:00:00 -s --mem=4G -- scripts/run_job.sh something else"
    )
    # Env-level default_setup / default_options are not baked into the
    # compiled cmd; the batch CLI applies them at submission.
    assert "module purge" not in stage["cmd"]
    assert "--account=foo" not in stage["cmd"]
    assert "scripts/run_job.sh" in stage["deps"]
    assert "data/input.txt" in stage["deps"]
    assert slurm_lock in stage["deps"]
    out = {"data/output.txt": {"cache": False, "persist": True}}
    assert out in stage["outs"]
    stage2 = stages["job2"]
    print(stage2)
    assert stage2["cmd"] == (
        "calkit slurm batch --name job2 --env-default-options ignore "
        "--env-default-setup ignore "
        "--environment slurm-env "
        "--dep something.jl --dep data/input2.txt --dep Manifest.toml "
        f"--dep {slurm_lock} "
        "--out data/output3.txt "
        "--setup 'module load gcc/12' --command "
        '-- calkit xenv -n julia1 --no-check -- "something.jl"'
    )
    assert "something.jl" in stage2["deps"]
    assert "data/input2.txt" in stage2["deps"]
    assert slurm_lock in stage2["deps"]
    assert "data/output3.txt" in stage2["outs"]
    # Even though the env defines default_setup, those entries don't end up
    # in the compiled stage cmd.
    assert "module purge" not in stage2["cmd"]
    assert "module load julia/1.11" not in stage2["cmd"]
    stage3 = stages["notebook"]
    print(stage3)
    assert stage3["cmd"] == (
        "calkit slurm batch --name notebook "
        "--environment slurm-env "
        "--dep .calkit/notebooks/cleaned/analysis.ipynb "
        "--dep data/input2.txt --dep Manifest.toml "
        f"--dep {slurm_lock} "
        "--out data/notebook_output.txt "
        "--out .calkit/notebooks/executed/analysis.ipynb "
        "--out .calkit/notebooks/html/analysis.html "
        "--command -- calkit nb execute --environment julia1 --no-check "
        '--to html "analysis.ipynb"'
    )
    assert ".calkit/notebooks/cleaned/analysis.ipynb" in stage3["deps"]
    assert "data/input2.txt" in stage3["deps"]
    assert slurm_lock in stage3["deps"]
    assert "data/notebook_output.txt" in stage3["outs"]
    py_stage = stages["py-job"]
    print(py_stage)
    assert py_stage["cmd"] == (
        "calkit slurm batch --name py-job "
        "--environment slurm-env "
        "--dep scripts/run.py --dep data/input_py.txt --dep uv.lock "
        f"--dep {slurm_lock} "
        "--out data/output_py.txt "
        "--command -- calkit xenv -n py1 --no-check -- "
        "python scripts/run.py --flag value"
    )
    assert "scripts/run.py" in py_stage["deps"]
    assert "data/input_py.txt" in py_stage["deps"]
    assert "uv.lock" in py_stage["deps"]
    assert slurm_lock in py_stage["deps"]
    r_stage = stages["r-job"]
    print(r_stage)
    assert r_stage["cmd"] == (
        "calkit slurm batch --name r-job "
        "--environment slurm-env "
        f"--dep scripts/run.R --dep renv.lock --dep {slurm_lock} "
        "--out data/output_r.txt "
        "--command -- calkit xenv -n r1 --no-check -- "
        "Rscript scripts/run.R"
    )
    assert "scripts/run.R" in r_stage["deps"]
    assert "renv.lock" in r_stage["deps"]
    assert slurm_lock in r_stage["deps"]
    sh_stage = stages["sh-cmd"]
    print(sh_stage)
    assert sh_stage["cmd"] == (
        "calkit slurm batch --name sh-cmd "
        "--environment slurm-env "
        f"--dep uv.lock --dep {slurm_lock} "
        "--command -- calkit xenv -n py1 --no-check -- "
        'bash --noprofile --norc -c "echo hi"'
    )
    assert "uv.lock" in sh_stage["deps"]
    assert slurm_lock in sh_stage["deps"]


def test_slurm_env_validation_rules(tmp_dir):
    """Cover the SLURM env-validation and plain-env shortcut rules.

    Scenarios:
    - language stage (python-script) on a plain slurm env errors and
      points users at composite-env syntax,
    - composite slurm:slurm env errors (no scheduler-in-scheduler),
    - shell-script on a plain slurm env compiles to a direct sbatch
      invocation with no inner xenv wrap,
    - shell-command on a plain slurm env wraps the command via
      ``--command -- bash -c``.
    """
    # Plain slurm env + a stage that needs an inner runtime should fail.
    with pytest.raises(ValueError, match="use a composite environment"):
        calkit.pipeline.to_dvc(
            ck_info={
                "environments": {"mycluster": {"kind": "slurm"}},
                "pipeline": {
                    "stages": {
                        "run": {
                            "kind": "python-script",
                            "script_path": "scripts/run.py",
                            "environment": "mycluster",
                        }
                    }
                },
            },
            write=False,
        )
    # Slurm-inside-slurm should fail.
    with pytest.raises(
        ValueError,
        match="inner environment must not be a job scheduler",
    ):
        calkit.pipeline.to_dvc(
            ck_info={
                "environments": {
                    "mycluster": {"kind": "slurm"},
                    "innercluster": {"kind": "slurm"},
                },
                "pipeline": {
                    "stages": {
                        "run": {
                            "kind": "julia-script",
                            "script_path": "scripts/run.jl",
                            "environment": "mycluster:innercluster",
                        }
                    }
                },
            },
            write=False,
        )
    # All non-language stage kinds compile on a plain slurm env:
    # shell-script (direct sbatch), shell-command (wrapped via bash -c),
    # and command (wrapped as-is via --command --).
    stages = calkit.pipeline.to_dvc(
        ck_info={
            "environments": {"mycluster": {"kind": "slurm"}},
            "pipeline": {
                "stages": {
                    "run-script": {
                        "kind": "shell-script",
                        "script_path": "scripts/run.sh",
                        "environment": "mycluster",
                        "args": ["a", "b"],
                    },
                    "run-shell-cmd": {
                        "kind": "shell-command",
                        "command": "echo hi",
                        "environment": "mycluster",
                    },
                    "run-cmd": {
                        "kind": "command",
                        "command": "mytool --flag",
                        "environment": "mycluster",
                    },
                }
            },
        },
        write=False,
    )
    assert stages["run-script"]["cmd"] == (
        "calkit slurm batch --name run-script "
        "--environment mycluster "
        "--dep .calkit/env-locks/mycluster.json "
        "-- scripts/run.sh a b"
    )
    assert stages["run-shell-cmd"]["cmd"] == (
        "calkit slurm batch --name run-shell-cmd "
        "--environment mycluster "
        "--dep .calkit/env-locks/mycluster.json "
        '--command -- bash --noprofile --norc -c "echo hi"'
    )
    assert stages["run-cmd"]["cmd"] == (
        "calkit slurm batch --name run-cmd "
        "--environment mycluster "
        "--dep .calkit/env-locks/mycluster.json "
        "--command -- mytool --flag"
    )


def test_pbs_stage_to_dvc(tmp_dir):
    """Cover the PBS stage compilation paths.

    Scenarios in one test:
    - shell-script on a plain pbs env compiles to a direct ``calkit sched
      batch`` invocation with stage-level options and outputs,
    - shell-command on a plain pbs env wraps the command via
      ``--command --``,
    - composite ``pbs-env:py1`` wrapping a python-script (default mode
      stays implicit),
    - composite ``pbs-env:r1`` wrapping an r-script,
    - composite ``pbs-env:py1`` wrapping a shell-command,
    - composite ``pbs-env:julia1`` wrapping a julia-script with
      stage-level setup and explicit ``env_default_*: ignore``,
    - composite ``pbs-env:julia1`` wrapping a jupyter-notebook,
    - env-level defaults are NOT baked into the compiled stage cmd (the
      batch CLI applies them at submission),
    - the env lock file is added as a dep on every stage that touches the
      pbs env.
    """
    envs = {
        "pbs-env": {
            "kind": "pbs",
            "default_setup": ["module purge", "module load julia/1.11"],
            "default_options": ["-A", "myproj"],
        },
        "julia1": {
            "kind": "julia",
            "julia": "1.11",
            "path": "Project.toml",
        },
        "py1": {"kind": "uv", "path": "pyproject.toml"},
        "r1": {"kind": "renv", "path": "DESCRIPTION"},
    }
    pipeline = {
        "stages": {
            "job1": {
                "kind": "shell-script",
                "script_path": "scripts/run_job.sh",
                "environment": "pbs-env",
                "args": ["something", "else"],
                "inputs": ["data/input.txt"],
                "outputs": [
                    {
                        "path": "data/output.txt",
                        "storage": "git",
                        "delete_before_run": False,
                    },
                    "data/output2.txt",
                ],
                "scheduler": {"options": ["-l", "walltime=01:00:00"]},
            },
            "job-cmd": {
                "kind": "shell-command",
                "command": "echo hello",
                "environment": "pbs-env",
            },
            # python-script in a composite pbs env.
            "py-job": {
                "kind": "python-script",
                "script_path": "scripts/run.py",
                "environment": "pbs-env:py1",
                "args": ["--flag", "value"],
                "inputs": ["data/input_py.txt"],
                "outputs": ["data/output_py.txt"],
            },
            # r-script in a composite pbs env.
            "r-job": {
                "kind": "r-script",
                "script_path": "scripts/run.R",
                "environment": "pbs-env:r1",
                "outputs": ["data/output_r.txt"],
            },
            # shell-command in a composite pbs env (inner runtime gets
            # an xenv wrap).
            "sh-cmd-nested": {
                "kind": "shell-command",
                "command": "echo hi",
                "environment": "pbs-env:py1",
            },
            "job2": {
                "kind": "julia-script",
                "script_path": "something.jl",
                "environment": "pbs-env:julia1",
                "inputs": ["data/input2.txt"],
                "outputs": ["data/output3.txt"],
                "scheduler": {
                    "setup": ["module load gcc/12"],
                    "env_default_options": "ignore",
                    "env_default_setup": "ignore",
                },
            },
            "notebook": {
                "kind": "jupyter-notebook",
                "notebook_path": "analysis.ipynb",
                "environment": "pbs-env:julia1",
                "html_storage": "dvc",
                "cleaned_ipynb_storage": None,
                "executed_ipynb_storage": "git",
                "inputs": ["data/input2.txt"],
                "outputs": ["data/notebook_output.txt"],
            },
        },
    }
    stages = calkit.pipeline.to_dvc(
        ck_info={
            "environments": envs,
            "pipeline": pipeline,
        },
        write=False,
    )
    pbs_lock = ".calkit/env-locks/pbs-env.json"
    stage = stages["job1"]
    print(stage)
    assert stage["cmd"] == (
        "calkit sched batch --name job1 "
        "--environment pbs-env "
        f"--dep data/input.txt --dep {pbs_lock} "
        "--out data/output2.txt "
        "-s -l -s walltime=01:00:00 "
        "-- scripts/run_job.sh something else"
    )
    # Env defaults stay out of the compiled cmd.
    assert "module purge" not in stage["cmd"]
    assert "myproj" not in stage["cmd"]
    assert pbs_lock in stage["deps"]
    out = {"data/output.txt": {"cache": False, "persist": True}}
    assert out in stage["outs"]
    stage_cmd = stages["job-cmd"]
    print(stage_cmd)
    assert stage_cmd["cmd"] == (
        "calkit sched batch --name job-cmd "
        "--environment pbs-env "
        f"--dep {pbs_lock} "
        '--command -- bash --noprofile --norc -c "echo hello"'
    )
    assert pbs_lock in stage_cmd["deps"]
    stage2 = stages["job2"]
    print(stage2)
    assert stage2["cmd"] == (
        "calkit sched batch --name job2 --env-default-options ignore "
        "--env-default-setup ignore "
        "--environment pbs-env "
        "--dep something.jl --dep data/input2.txt --dep Manifest.toml "
        f"--dep {pbs_lock} "
        "--out data/output3.txt "
        "--setup 'module load gcc/12' --command "
        '-- calkit xenv -n julia1 --no-check -- "something.jl"'
    )
    assert pbs_lock in stage2["deps"]
    stage3 = stages["notebook"]
    print(stage3)
    assert stage3["cmd"] == (
        "calkit sched batch --name notebook "
        "--environment pbs-env "
        "--dep .calkit/notebooks/cleaned/analysis.ipynb "
        "--dep data/input2.txt --dep Manifest.toml "
        f"--dep {pbs_lock} "
        "--out data/notebook_output.txt "
        "--out .calkit/notebooks/executed/analysis.ipynb "
        "--out .calkit/notebooks/html/analysis.html "
        "--command -- calkit nb execute --environment julia1 --no-check "
        '--to html "analysis.ipynb"'
    )
    assert pbs_lock in stage3["deps"]
    py_stage = stages["py-job"]
    print(py_stage)
    assert py_stage["cmd"] == (
        "calkit sched batch --name py-job "
        "--environment pbs-env "
        "--dep scripts/run.py --dep data/input_py.txt --dep uv.lock "
        f"--dep {pbs_lock} "
        "--out data/output_py.txt "
        "--command -- calkit xenv -n py1 --no-check -- "
        "python scripts/run.py --flag value"
    )
    assert "scripts/run.py" in py_stage["deps"]
    assert "data/input_py.txt" in py_stage["deps"]
    assert "uv.lock" in py_stage["deps"]
    assert pbs_lock in py_stage["deps"]
    r_stage = stages["r-job"]
    print(r_stage)
    assert r_stage["cmd"] == (
        "calkit sched batch --name r-job "
        "--environment pbs-env "
        f"--dep scripts/run.R --dep renv.lock --dep {pbs_lock} "
        "--out data/output_r.txt "
        "--command -- calkit xenv -n r1 --no-check -- "
        "Rscript scripts/run.R"
    )
    assert "scripts/run.R" in r_stage["deps"]
    assert "renv.lock" in r_stage["deps"]
    assert pbs_lock in r_stage["deps"]
    sh_nested = stages["sh-cmd-nested"]
    print(sh_nested)
    assert sh_nested["cmd"] == (
        "calkit sched batch --name sh-cmd-nested "
        "--environment pbs-env "
        f"--dep uv.lock --dep {pbs_lock} "
        "--command -- calkit xenv -n py1 --no-check -- "
        'bash --noprofile --norc -c "echo hi"'
    )
    assert "uv.lock" in sh_nested["deps"]
    assert pbs_lock in sh_nested["deps"]


def test_pbs_env_validation_rules(tmp_dir):
    """Cover the PBS env-validation and plain-env shortcut rules.

    Mirrors ``test_slurm_env_validation_rules`` for PBS, plus the
    cross-scheduler case (pbs outer, slurm inner) which is also rejected.
    """
    with pytest.raises(ValueError, match="use a composite environment"):
        calkit.pipeline.to_dvc(
            ck_info={
                "environments": {"mycluster": {"kind": "pbs"}},
                "pipeline": {
                    "stages": {
                        "run": {
                            "kind": "python-script",
                            "script_path": "scripts/run.py",
                            "environment": "mycluster",
                        }
                    }
                },
            },
            write=False,
        )
    with pytest.raises(
        ValueError,
        match="inner environment must not be a job scheduler",
    ):
        calkit.pipeline.to_dvc(
            ck_info={
                "environments": {
                    "mycluster": {"kind": "pbs"},
                    "innercluster": {"kind": "pbs"},
                },
                "pipeline": {
                    "stages": {
                        "run": {
                            "kind": "julia-script",
                            "script_path": "scripts/run.jl",
                            "environment": "mycluster:innercluster",
                        }
                    }
                },
            },
            write=False,
        )
    # Mixing schedulers (pbs outer, slurm inner) should also fail.
    with pytest.raises(
        ValueError,
        match="inner environment must not be a job scheduler",
    ):
        calkit.pipeline.to_dvc(
            ck_info={
                "environments": {
                    "mypbs": {"kind": "pbs"},
                    "myslurm": {"kind": "slurm"},
                },
                "pipeline": {
                    "stages": {
                        "run": {
                            "kind": "julia-script",
                            "script_path": "scripts/run.jl",
                            "environment": "mypbs:myslurm",
                        }
                    }
                },
            },
            write=False,
        )
    # All non-language stage kinds compile on a plain pbs env:
    # shell-script (direct qsub), shell-command (wrapped via bash -c),
    # and command (wrapped as-is via --command --).
    stages = calkit.pipeline.to_dvc(
        ck_info={
            "environments": {"mycluster": {"kind": "pbs"}},
            "pipeline": {
                "stages": {
                    "run-script": {
                        "kind": "shell-script",
                        "script_path": "scripts/run.sh",
                        "environment": "mycluster",
                        "args": ["a", "b"],
                    },
                    "run-shell-cmd": {
                        "kind": "shell-command",
                        "command": "echo hi",
                        "environment": "mycluster",
                    },
                    "run-cmd": {
                        "kind": "command",
                        "command": "mytool --flag",
                        "environment": "mycluster",
                    },
                }
            },
        },
        write=False,
    )
    assert stages["run-script"]["cmd"] == (
        "calkit sched batch --name run-script "
        "--environment mycluster "
        "--dep .calkit/env-locks/mycluster.json "
        "-- scripts/run.sh a b"
    )
    assert stages["run-shell-cmd"]["cmd"] == (
        "calkit sched batch --name run-shell-cmd "
        "--environment mycluster "
        "--dep .calkit/env-locks/mycluster.json "
        '--command -- bash --noprofile --norc -c "echo hi"'
    )
    assert stages["run-cmd"]["cmd"] == (
        "calkit sched batch --name run-cmd "
        "--environment mycluster "
        "--dep .calkit/env-locks/mycluster.json "
        "--command -- mytool --flag"
    )


def test_generic_scheduler_key(tmp_dir):
    """The generic ``scheduler:`` key resolves to the env's scheduler kind.

    Scenarios:
    - ``scheduler:`` on a SLURM env compiles identically to ``slurm:``,
    - ``scheduler:`` on a PBS env compiles identically to ``pbs:``,
    - setting both ``scheduler:`` and ``slurm:`` (or ``pbs:``) is rejected
      at model validation time.
    """
    slurm_stages = calkit.pipeline.to_dvc(
        ck_info={
            "environments": {"mycluster": {"kind": "slurm"}},
            "pipeline": {
                "stages": {
                    "run": {
                        "kind": "shell-script",
                        "script_path": "scripts/run.sh",
                        "environment": "mycluster",
                        "scheduler": {"options": ["--time=01:00:00"]},
                    }
                }
            },
        },
        write=False,
    )
    assert "-s --time=01:00:00" in slurm_stages["run"]["cmd"]
    assert "calkit slurm batch" in slurm_stages["run"]["cmd"]
    pbs_stages = calkit.pipeline.to_dvc(
        ck_info={
            "environments": {"mycluster": {"kind": "pbs"}},
            "pipeline": {
                "stages": {
                    "run": {
                        "kind": "shell-script",
                        "script_path": "scripts/run.sh",
                        "environment": "mycluster",
                        "scheduler": {"options": ["-l", "walltime=01:00:00"]},
                    }
                }
            },
        },
        write=False,
    )
    assert "-s -l -s walltime=01:00:00" in pbs_stages["run"]["cmd"]
    assert "calkit sched batch" in pbs_stages["run"]["cmd"]
    # Setting both scheduler: and slurm: should fail at parse time.
    with pytest.raises(ValueError, match="both 'slurm' and 'scheduler'"):
        calkit.pipeline.to_dvc(
            ck_info={
                "environments": {"mycluster": {"kind": "slurm"}},
                "pipeline": {
                    "stages": {
                        "run": {
                            "kind": "shell-script",
                            "script_path": "scripts/run.sh",
                            "environment": "mycluster",
                            "slurm": {"options": ["--time=01:00:00"]},
                            "scheduler": {"options": ["--time=02:00:00"]},
                        }
                    }
                },
            },
            write=False,
        )


def test_gitignore_updated_when_stage_output_renamed(tmp_dir):
    """When a stage output path is renamed, stale .gitignore entries are
    replaced.

    Use the .gitignore contents for verification because case-only renames can
    still appear ignored on case-insensitive filesystems like the default macOS
    setup.
    """
    subprocess.check_call(["calkit", "init"])
    # Stage 1: initial calkit.yaml with output 'b_sparsity_plot.pdf' stored in DVC
    ck_info = {
        "pipeline": {
            "stages": {
                "plot": {
                    "kind": "command",
                    "environment": "_system",
                    "command": "touch b_sparsity_plot.pdf",
                    "outputs": [
                        {
                            "path": "b_sparsity_plot.pdf",
                            "storage": "dvc",
                        }
                    ],
                }
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"])
    # Verify DVC has added the old output path to .gitignore
    repo = git.Repo(".")
    assert repo.ignored("b_sparsity_plot.pdf")
    with open(".gitignore") as f:
        lines = f.read().splitlines()
    assert "/b_sparsity_plot.pdf" in lines
    # Stage 2: rename output (capitalization change) to 'B_sparsity_plot.pdf'
    ck_info["pipeline"]["stages"]["plot"]["command"] = (
        "touch B_sparsity_plot.pdf"
    )
    ck_info["pipeline"]["stages"]["plot"]["outputs"] = [
        {"path": "B_sparsity_plot.pdf", "storage": "dvc"}
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"])
    with open(".gitignore") as f:
        lines = f.read().splitlines()
    assert "/b_sparsity_plot.pdf" not in lines
    assert "/B_sparsity_plot.pdf" in lines
    assert repo.ignored("B_sparsity_plot.pdf")


def test_gitignore_not_unignored_latex_pdf_output(tmp_dir):
    repo = git.Repo.init()
    subprocess.check_call(["calkit", "init"])
    os.makedirs("paper", exist_ok=True)
    with open("paper/.gitignore", "w") as f:
        f.write("/main.pdf\n")
    ck_info = {
        "environments": {
            "tex": {
                "kind": "conda",
                "path": "environment.yaml",
            }
        },
        "pipeline": {
            "stages": {
                "build-paper": {
                    "kind": "latex",
                    "environment": "tex",
                    "target_path": "paper/main.tex",
                    "force": True,
                    "inputs": [
                        "paper/references.bib",
                        "paper/aasjournal.bst",
                        "paper/aastex631.cls",
                        "paper/results.tex",
                        "paper/diagrams",
                        "paper/figures",
                    ],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
    assert not os.path.exists(".gitignore")
    assert repo.ignored("paper/main.pdf")
    calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
    assert not os.path.exists(".gitignore")
    with open("paper/.gitignore") as f:
        assert f.read().splitlines() == ["/main.pdf"]
    assert repo.ignored("paper/main.pdf")


def test_get_status(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "prefix": ".venv",
            }
        },
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "something/my-cool-script.py",
                    "outputs": [
                        "my-output.out",
                    ],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    os.makedirs("something", exist_ok=True)
    with open("something/my-cool-script.py", "w") as f:
        f.write(
            "with open('my-output.out', 'w') as f:\n"
            "    f.write('Hello, world!')\n"
        )
    status = calkit.pipeline.get_status(ck_info=ck_info)
    assert not status.failed_environment_checks
    assert status.is_stale
    assert "get-data" in status.stale_stage_names
    assert status.stale_stages["get-data"].stale_outputs == ["my-output.out"]
    assert status.stale_stages["get-data"].modified_outputs == []
    # Run the pipeline and check that status updates to up-to-date
    subprocess.check_call(["calkit", "run"])
    status = calkit.pipeline.get_status(ck_info=ck_info)
    assert not status.failed_environment_checks
    assert not status.is_stale
    assert not status.stale_stage_names
    # Now manually modify the output and ensure we have a changed output, but
    # not a stale output
    with open("my-output.out", "w") as f:
        f.write("Goodbye, world!")
    status = calkit.pipeline.get_status(ck_info=ck_info)
    assert not status.failed_environment_checks
    assert status.is_stale
    assert status.stale_stages["get-data"].modified_outputs == [
        "my-output.out"
    ]
    assert status.stale_stages["get-data"].stale_outputs == []
    # Now change the output back to the original, but modify the script so we
    # can check we have stale outputs due to changed dependencies
    # TODO: Should we distinguish between a changed script and a changed input?
    # Technically in the stage definition there are no inputs
    with open("my-output.out", "w") as f:
        f.write("Hello, world!")
    with open("something/my-cool-script.py", "w") as f:
        f.write(
            "with open('my-output.out', 'w') as f:\n"
            "    f.write('Hello again, world!')\n"
        )
    status = calkit.pipeline.get_status(ck_info=ck_info)
    assert not status.failed_environment_checks
    assert status.is_stale
    assert status.stale_stages["get-data"].modified_inputs == [
        "something/my-cool-script.py"
    ]
    assert status.stale_stages["get-data"].stale_outputs == ["my-output.out"]
    assert status.stale_stages["get-data"].modified_outputs == []


def test_stale_stage_detects_changed_command():
    stale_stage = calkit.pipeline.StaleStage.from_status_data(
        status_data=[{"changed command": "python src/new-script.py"}],
        configured_outputs=["my-output.out"],
    )
    assert stale_stage.modified_command
    assert stale_stage.stale_outputs == ["my-output.out"]
    assert stale_stage.modified_inputs == []
    assert stale_stage.modified_outputs == []


def test_stale_stage_path_prefix():
    # Isolated subproject paths are subproject-relative from DVC's perspective;
    # path_prefix makes them parent-relative for consistent status display.
    status_data = [
        {
            "changed deps": {"report/main.tex": "modified"},
            "changed outs": {"report/main.pdf": "not in cache"},
        }
    ]
    stale = calkit.pipeline.StaleStage.from_status_data(
        status_data=status_data,
        configured_outputs=["sub2/report/main.pdf"],
        path_prefix="sub2",
    )
    # All paths must be parent-relative
    assert stale.modified_inputs == ["sub2/report/main.tex"]
    assert all(p.startswith("sub2/") for p in stale.stale_outputs)
    # Cross-subproject dep via "../" should be normalized to parent-relative
    status_data_cross = [{"changed deps": {"../shared.txt": "modified"}}]
    stale_cross = calkit.pipeline.StaleStage.from_status_data(
        status_data=status_data_cross,
        configured_outputs=[],
        path_prefix="solver",
    )
    assert stale_cross.modified_inputs == ["shared.txt"]


def test_collapse_dvc_stages():
    def out_paths(stage):
        return {
            list(o.keys())[0] if isinstance(o, dict) else o
            for o in stage.get("outs", [])
        }

    # Basic case: internal deps are not surfaced; external ones are.
    stages = {
        "stage-a": {
            "cmd": "echo hi",
            "deps": ["../external.txt"],
            "outs": ["internal.txt"],
        },
        "stage-b": {
            "cmd": "echo hi",
            "deps": ["internal.txt"],
            "outs": [{"result.txt": {"cache": False}}],
        },
    }
    collapsed = collapse_dvc_stages(
        stages, cmd="calkit dvc repro", wdir="sub1", desc="wrapper"
    )
    assert collapsed["cmd"] == "calkit dvc repro"
    assert collapsed["wdir"] == "sub1"
    assert collapsed["desc"] == "wrapper"
    assert collapsed["deps"] == ["../external.txt"]
    assert out_paths(collapsed) == {"internal.txt", "result.txt"}
    # All outs are wrapped with cache:false persist:true.
    for o in collapsed["outs"]:
        assert isinstance(o, dict)
        assert list(o.values())[0] == {"cache": False, "persist": True}
    # Without optional args the keys are absent.
    minimal = collapse_dvc_stages(stages)
    assert "cmd" not in minimal
    assert "wdir" not in minimal
    assert "desc" not in minimal
    # Clean case: no always_changed when there is no folder-ancestor drop.
    assert "always_changed" not in collapsed
    assert "always_changed" not in minimal
    # Folder dep that contains output files: dep must be dropped and
    # always_changed set.  Mirrors the real-world scenario where a stage reads
    # ``pubs/JFM/figs`` (a pre-existing directory) while another stage writes
    # individual files into that same directory.
    stages2 = {
        "stage-a": {
            "cmd": "echo hi",
            "deps": ["../in.txt", "pubs/JFM/figs"],
            "outs": ["listing.txt"],
        },
        "stage-b": {
            "cmd": "echo hi",
            "deps": ["listing.txt"],
            "outs": ["pubs/JFM/figs/plot.pdf", "pubs/JFM/figs/other.pdf"],
        },
    }
    collapsed2 = collapse_dvc_stages(stages2)
    assert "pubs/JFM/figs" not in collapsed2["deps"]
    assert "../in.txt" in collapsed2["deps"]
    assert "pubs/JFM/figs/plot.pdf" in out_paths(collapsed2)
    assert "pubs/JFM/figs/other.pdf" in out_paths(collapsed2)
    assert collapsed2.get("always_changed") is True
    # Descendant case: dep is inside an output folder — this is a normal
    # internal drop and must NOT set always_changed.
    stages2b = {
        "stage-a": {
            "cmd": "echo hi",
            "deps": ["../in.txt"],
            "outs": ["data/"],
        },
        "stage-b": {
            "cmd": "echo hi",
            "deps": ["data/file.csv"],
            "outs": ["result.txt"],
        },
    }
    collapsed2b = collapse_dvc_stages(stages2b)
    assert "always_changed" not in collapsed2b
    # Exact-match aliasing: "./file.txt" and "file.txt" must not both appear.
    stages3 = {
        "stage-a": {
            "cmd": "echo hi",
            "deps": ["../in.txt"],
            "outs": ["file.txt"],
        },
        "stage-b": {
            "cmd": "echo hi",
            "deps": ["./file.txt"],
            "outs": ["out.txt"],
        },
    }
    collapsed3 = collapse_dvc_stages(stages3)
    all_paths3 = set(collapsed3["deps"]) | out_paths(collapsed3)
    # "file.txt" and "./file.txt" normalize to the same path; no duplicates.
    assert len([p for p in all_paths3 if p in ("file.txt", "./file.txt")]) <= 1
    # env-lock paths in deps are kept so the wrapper goes stale when a
    # subproject lock file changes.
    stages4 = {
        "stage-a": {
            "cmd": "echo hi",
            "deps": [".calkit/env-locks/main", "../external.txt"],
            "outs": ["output.txt"],
        },
    }
    collapsed4 = collapse_dvc_stages(stages4)
    assert ".calkit/env-locks/main" in collapsed4["deps"]
    # Matrix stage: template variables are expanded before deduplication.
    stages5 = {
        "stage-m": {
            "cmd": "echo ${item.n}",
            "matrix": {"n": [1, 2]},
            "deps": ["../shared.txt"],
            "outs": ["out_${item.n}.txt"],
        },
    }
    collapsed5 = collapse_dvc_stages(stages5)
    assert collapsed5["deps"] == ["../shared.txt"]
    assert out_paths(collapsed5) == {"out_1.txt", "out_2.txt"}


def test_wrapper_stage_no_dep_out_overlap(tmp_dir):
    """Wrapper stage deps and outs must never overlap.

    Covers:
    - Path normalization: ``./out.txt`` and ``out.txt`` are the same file;
      without normalization the set-subtraction misses this and both could
      appear in wrapper deps and outs simultaneously.
    - Defensive deduplication: even if normalization is bypassed, the
      explicit dedup pass keeps such paths only as deps.
    """
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["git", "config", "user.email", "t@t.com"])
    subprocess.check_call(["git", "config", "user.name", "T"])
    os.makedirs("isolated")
    subprocess.check_call(["git", "init"], cwd="isolated")
    subprocess.check_call(
        ["git", "config", "user.email", "t@t.com"], cwd="isolated"
    )
    subprocess.check_call(["git", "config", "user.name", "T"], cwd="isolated")
    subprocess.check_call(["dvc", "init"], cwd="isolated")
    # Two stages: stage-a reads an external dep (with leading ./) and produces
    # internal.txt; stage-b reads internal.txt (no ./) and produces result.txt.
    # The leading "./" on the external dep is the normalization hazard.
    with open("isolated/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "stage-a": {
                            "kind": "command",
                            "environment": "_system",
                            "command": "cat ../external.txt > internal.txt",
                            "inputs": ["../external.txt"],
                            "outputs": [
                                {"path": "internal.txt", "storage": "git"}
                            ],
                        },
                        "stage-b": {
                            "kind": "command",
                            "environment": "_system",
                            "command": "cat internal.txt > result.txt",
                            "inputs": ["internal.txt"],
                            "outputs": [
                                {"path": "result.txt", "storage": "git"}
                            ],
                        },
                    }
                }
            },
            f,
        )
    # Compile subproject pipeline first so it has a dvc.yaml
    calkit.pipeline.to_dvc(wdir="isolated", write=True, manage_gitignore=False)
    # Inject a "./"-prefixed dep into the compiled dvc.yaml to simulate the
    # path-aliasing scenario that caused the MDOcean/OpenFLASH error.
    with open("isolated/dvc.yaml") as f:
        isolated_dvc = calkit.ryaml.load(f)
    if "stage-b" in isolated_dvc.get("stages", {}):
        stage_b = isolated_dvc["stages"]["stage-b"]
        # Replace the plain dep with the ./-prefixed variant
        stage_b["deps"] = [
            "./" + d if d == "internal.txt" else d
            for d in stage_b.get("deps", [])
        ]
    with open("isolated/dvc.yaml", "w") as f:
        calkit.ryaml.dump(isolated_dvc, f)
    # Build parent pipeline referencing the isolated subproject
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {"subprojects": [{"path": "isolated"}]},
            f,
        )
    with open("external.txt", "w") as f:
        f.write("data")
    dvc_stages = calkit.pipeline.to_dvc(write=False, manage_gitignore=False)
    wrapper = dvc_stages.get("isolated", {})
    assert wrapper, "wrapper stage not generated"
    wrapper_dep_set = set(wrapper.get("deps", []))
    wrapper_out_paths = {
        list(o.keys())[0] if isinstance(o, dict) else o
        for o in wrapper.get("outs", [])
    }
    overlap = wrapper_dep_set & wrapper_out_paths
    assert not overlap, f"wrapper has dep/out overlap: {overlap}"
    # Tree-overlap case: a folder dep whose contents include output files.
    # stage-c reads an external folder ``figs`` and stage-d writes a file
    # inside it.  The wrapper must not list ``figs`` as a dep while also
    # listing ``figs/plot.pdf`` as an out.
    with open("isolated/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "stage-c": {
                            "kind": "command",
                            "environment": "_system",
                            "command": "ls ../figs > listing.txt",
                            "inputs": ["../figs"],
                            "outputs": [
                                {"path": "listing.txt", "storage": "git"}
                            ],
                        },
                        "stage-d": {
                            "kind": "command",
                            "environment": "_system",
                            "command": "cp listing.txt figs/plot.pdf",
                            "inputs": ["listing.txt"],
                            "outputs": [
                                {"path": "figs/plot.pdf", "storage": "git"}
                            ],
                        },
                    }
                }
            },
            f,
        )
    os.makedirs("figs", exist_ok=True)
    calkit.pipeline.to_dvc(wdir="isolated", write=True, manage_gitignore=False)
    dvc_stages2 = calkit.pipeline.to_dvc(write=False, manage_gitignore=False)
    wrapper2 = dvc_stages2.get("isolated", {})
    assert wrapper2, "wrapper stage not generated"
    wrapper2_deps = wrapper2.get("deps", [])
    wrapper2_out_paths = {
        list(o.keys())[0] if isinstance(o, dict) else o
        for o in wrapper2.get("outs", [])
    }
    # ``../figs`` in the subproject is the external dep; after normalization
    # it becomes a parent-relative path.  No dep should tree-overlap any out.
    from calkit.pipeline import _paths_overlap

    for dep in wrapper2_deps:
        for out in wrapper2_out_paths:
            assert not _paths_overlap(
                dep, out
            ), f"wrapper dep '{dep}' tree-overlaps out '{out}'"


def test_expand_dep_excluding_subprojects(tmp_dir):
    # Directory dep not containing any isolated subproject returns as-is
    os.makedirs("src")
    open("src/a.py", "w").close()
    result = _expand_dep_excluding_subprojects("src", [])
    assert result == ["src"]
    # Directory dep containing an isolated subproject is expanded to siblings
    os.makedirs("sim/modules/SubProj/.dvc")
    open("sim/modules/other.py", "w").close()
    open("sim/run.py", "w").close()
    result = _expand_dep_excluding_subprojects("sim", ["sim/modules/SubProj"])
    assert "sim/run.py" in result
    assert "sim/modules/other.py" in result
    # The isolated subproject itself must not appear in the expansion
    assert not any("SubProj" in r for r in result)
    # A dep that is not a directory returns as-is
    result = _expand_dep_excluding_subprojects(
        "sim/run.py", ["sim/modules/SubProj"]
    )
    assert result == ["sim/run.py"]


def test_translate_run_targets(tmp_dir):
    # Set up a parent project with one inline subproject and one isolated.
    subprocess.check_call(["git", "init"])
    os.makedirs("inline-sp/calkit", exist_ok=True)
    os.makedirs("isolated-sp/.dvc", exist_ok=True)
    with open("inline-sp/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "stage-a": {
                            "kind": "shell-command",
                            "command": "echo a",
                            "environment": "env",
                        }
                    }
                }
            },
            f,
        )
    with open("isolated-sp/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "stage-b": {
                            "kind": "shell-command",
                            "command": "echo b",
                            "environment": "env",
                        }
                    }
                }
            },
            f,
        )
    ck_info = {
        "subprojects": [
            {"path": "inline-sp"},
            {"path": "isolated-sp"},
        ]
    }
    # Inline subproject: name → dvc.yaml path
    parent, isolated = calkit.pipeline.translate_run_targets(
        ["inline-sp"], ck_info=ck_info
    )
    assert parent == ["inline-sp/dvc.yaml"]
    assert isolated == []
    # Inline subproject: name:stage → dvc.yaml:stage
    parent, isolated = calkit.pipeline.translate_run_targets(
        ["inline-sp:stage-a"], ck_info=ck_info
    )
    assert parent == ["inline-sp/dvc.yaml:stage-a"]
    assert isolated == []
    # Isolated subproject: name → wrapper stage
    parent, isolated = calkit.pipeline.translate_run_targets(
        ["isolated-sp"], ck_info=ck_info
    )
    assert parent == ["isolated-sp"]
    assert isolated == []
    # Isolated subproject: name:stage → isolated_sp_targets
    parent, isolated = calkit.pipeline.translate_run_targets(
        ["isolated-sp:stage-b"], ck_info=ck_info
    )
    assert parent == []
    assert isolated == [("isolated-sp", "stage-b")]
    # Unrecognized targets pass through unchanged
    parent, isolated = calkit.pipeline.translate_run_targets(
        ["my-parent-stage"], ck_info=ck_info
    )
    assert parent == ["my-parent-stage"]
    assert isolated == []
    # Mixed: inline stage + isolated stage + plain parent stage
    parent, isolated = calkit.pipeline.translate_run_targets(
        ["inline-sp:stage-a", "isolated-sp:stage-b", "my-parent-stage"],
        ck_info=ck_info,
    )
    assert parent == ["inline-sp/dvc.yaml:stage-a", "my-parent-stage"]
    assert isolated == [("isolated-sp", "stage-b")]
