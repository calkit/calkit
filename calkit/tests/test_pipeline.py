"""Tests for ``calkit.pipeline``."""

import os
import subprocess

import git
import pytest

import calkit
import calkit.pipeline
from calkit.environments import get_env_lock_fpath
from calkit.pipeline import stages_are_similar


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


def test_sbatch_stage_to_dvc():
    envs = {
        "slurm-env": {"kind": "slurm"},
        "julia1": {
            "kind": "julia",
            "julia": "1.11",
            "path": "Project.toml",
        },
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
            # Test nested env with slurm outer
            "job2": {
                "kind": "julia-script",
                "script_path": "something.jl",
                "environment": "slurm-env:julia1",
                "inputs": ["data/input2.txt"],
                "outputs": ["data/output3.txt"],
            },
            # Test jupyter-notebook stage in nested env with slurm outer
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
    stage = stages["job1"]
    print(stage)
    assert stage["cmd"] == (
        "calkit slurm batch --name job1 --environment slurm-env "
        "--dep data/input.txt --out data/output2.txt "
        "-s --time=01:00:00 -s --mem=4G -- scripts/run_job.sh something else"
    )
    assert "scripts/run_job.sh" in stage["deps"]
    assert "data/input.txt" in stage["deps"]
    out = {"data/output.txt": {"cache": False, "persist": True}}
    assert out in stage["outs"]
    stage2 = stages["job2"]
    print(stage2)
    assert stage2["cmd"] == (
        "calkit slurm batch --name job2 --environment slurm-env "
        "--dep something.jl --dep data/input2.txt --dep Manifest.toml "
        "--out data/output3.txt --command "
        '-- calkit xenv -n julia1 --no-check -- "something.jl"'
    )
    assert "something.jl" in stage2["deps"]
    assert "data/input2.txt" in stage2["deps"]
    assert "data/output3.txt" in stage2["outs"]
    stage3 = stages["notebook"]
    print(stage3)
    assert stage3["cmd"] == (
        "calkit slurm batch --name notebook --environment slurm-env "
        "--dep .calkit/notebooks/cleaned/analysis.ipynb "
        "--dep data/input2.txt --dep Manifest.toml "
        "--out data/notebook_output.txt "
        "--out .calkit/notebooks/executed/analysis.ipynb "
        "--out .calkit/notebooks/html/analysis.html "
        "--command -- calkit nb execute --environment julia1 --no-check "
        '--to html "analysis.ipynb"'
    )
    assert ".calkit/notebooks/cleaned/analysis.ipynb" in stage3["deps"]
    assert "data/input2.txt" in stage3["deps"]
    assert "data/notebook_output.txt" in stage3["outs"]


def test_slurm_setup_commands_propagate_to_nested_stage_cmd():
    envs = {
        "slurm-env": {
            "kind": "slurm",
            "default_setup": ["module purge", "module load julia/1.11"],
        },
        "julia1": {
            "kind": "julia",
            "julia": "1.11",
            "path": "Project.toml",
        },
    }
    pipeline = {
        "stages": {
            "job1": {
                "kind": "julia-script",
                "script_path": "something.jl",
                "environment": "slurm-env:julia1",
                "slurm": {
                    "setup": ["module load gcc/12"],
                },
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
    cmd = stages["job1"]["cmd"]
    assert "--setup 'module purge'" in cmd
    assert "--setup 'module load julia/1.11'" in cmd
    assert "--setup 'module load gcc/12'" in cmd
    assert "--command -- calkit xenv -n julia1 --no-check --" in cmd


def test_non_sbatch_stage_requires_composite_slurm_env():
    envs = {
        "mycluster": {"kind": "slurm"},
    }
    pipeline = {
        "stages": {
            "run": {
                "kind": "python-script",
                "script_path": "scripts/run.py",
                "environment": "mycluster",
            }
        }
    }
    with pytest.raises(ValueError, match="Use a composite environment"):
        calkit.pipeline.to_dvc(
            ck_info={
                "environments": envs,
                "pipeline": pipeline,
            },
            write=False,
        )


def test_non_sbatch_stage_disallows_slurm_inner_env():
    envs = {
        "mycluster": {"kind": "slurm"},
        "innercluster": {"kind": "slurm"},
    }
    pipeline = {
        "stages": {
            "run": {
                "kind": "julia-script",
                "script_path": "scripts/run.jl",
                "environment": "mycluster:innercluster",
            }
        }
    }
    with pytest.raises(
        ValueError,
        match="inner environment.*must not be SLURM",
    ):
        calkit.pipeline.to_dvc(
            ck_info={
                "environments": envs,
                "pipeline": pipeline,
            },
            write=False,
        )


def test_shell_script_stage_allows_non_composite_slurm_env():
    envs = {
        "mycluster": {"kind": "slurm"},
    }
    pipeline = {
        "stages": {
            "run": {
                "kind": "shell-script",
                "script_path": "scripts/run.sh",
                "environment": "mycluster",
                "args": ["a", "b"],
            }
        }
    }
    stages = calkit.pipeline.to_dvc(
        ck_info={
            "environments": envs,
            "pipeline": pipeline,
        },
        write=False,
    )
    assert stages["run"]["cmd"] == (
        "calkit slurm batch --name run --environment mycluster "
        "-- scripts/run.sh a b"
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
    wrapper = dvc_stages.get("_subproject-isolated", {})
    assert wrapper, "wrapper stage not generated"
    wrapper_dep_set = set(wrapper.get("deps", []))
    wrapper_out_paths = {
        list(o.keys())[0] if isinstance(o, dict) else o
        for o in wrapper.get("outs", [])
    }
    overlap = wrapper_dep_set & wrapper_out_paths
    assert not overlap, f"wrapper has dep/out overlap: {overlap}"


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
    assert parent == ["_subproject-isolated-sp"]
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
