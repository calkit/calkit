"""Tests for the ``calkit xr`` command."""

import json
import os
import re
import shutil
import subprocess

import pytest
import toml

import calkit


def test_xr_python_script(tmp_dir):
    """Test xr command with Python script."""
    # Create a simple Python script with I/O
    script_path = "process_data.py"
    stage_name = "process-data"
    with open(script_path, "w") as f:
        f.write("""#!/usr/bin/env python

import sys, time
import numpy as np

# Read input
with open('input.txt', 'r') as f:
    data = f.read()

# Write output
with open('output.txt', 'w') as f:
    f.write(data.upper())

print("Processing complete")
""")
    # Create input file
    with open("input.txt", "w") as f:
        f.write("hello world")
    # Execute and record
    result = subprocess.run(
        ["calkit", "xr", script_path],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    assert "Processing complete" in result.stdout
    # Verify stage was added to pipeline
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert stage_name in stages
    stage = stages[stage_name]
    assert stage["kind"] == "python-script"
    assert stage["script_path"] == script_path
    assert stage["environment"] == "main"
    env = ck_info["environments"]["main"]
    assert env["kind"] == "uv"
    assert env["path"] == "pyproject.toml"
    # Read pyproject.toml to check that numpy is listed as a dependency
    with open("pyproject.toml", "r") as f:
        pyproject = toml.load(f)
        deps = pyproject["project"]["dependencies"]
        deps = [re.split("[><=]", dep.strip())[0] for dep in deps]
        assert "numpy" in deps
    # Verify I/O detection
    assert "input.txt" in stage["inputs"]
    # Check output was created
    assert os.path.exists("output.txt")
    with open("output.txt", "r") as f:
        assert f.read() == "HELLO WORLD"
    # Verify output was detected
    outputs = stage.get("outputs", [])
    output_paths = [
        out["path"] if isinstance(out, dict) else out for out in outputs
    ]
    assert "output.txt" in output_paths


def test_xr_shell_command(tmp_dir):
    """Test xr command with shell command."""
    subprocess.check_call(["calkit", "init"])
    # Create a simple docker environment for shell commands
    subprocess.check_call(
        [
            "calkit",
            "new",
            "docker-env",
            "-n",
            "shell-env",
            "--image",
            "shell-env",
            "--from",
            "ubuntu",
        ]
    )
    # Execute shell command
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "echo",
            "Hello World",
            "--stage",
            "greet",
            "-e",
            "shell-env",
        ],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    assert "Hello World" in result.stdout
    # Verify stage was added
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "greet" in stages
    stage = stages["greet"]
    assert stage["kind"] == "shell-command"
    assert stage["command"] == "echo 'Hello World'"
    assert stage["environment"] == "shell-env"


def test_xr_mermaid_docker_command_dry_run(tmp_dir):
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "--dry-run",
            "--json",
            "--environment",
            "mermaid",
            (
                "docker run --rm -u 1000:1000 "
                "-v ./mdocean/plots/non_matlab_figs:/data "
                "minlag/mermaid-cli "
                "-i taxonomy.mmd -o taxonomy.pdf"
            ),
        ],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["environment"]["name"] == "mermaid"
    assert payload["environment"]["exists"] is False
    assert payload["environment"]["env"] == {
        "kind": "docker",
        "image": "minlag/mermaid-cli:latest",
        "description": "Mermaid CLI via Docker.",
        "wdir": "/data",
        "command_mode": "entrypoint",
    }
    assert payload["stage"]["name"] == "mermaid-taxonomy"
    assert payload["stage"]["stage"]["kind"] == "command"
    assert payload["stage"]["stage"]["environment"] == "mermaid"
    assert payload["stage"]["stage"]["command"] == (
        "-i mdocean/plots/non_matlab_figs/taxonomy.mmd "
        "-o mdocean/plots/non_matlab_figs/taxonomy.pdf"
    )
    assert payload["stage"]["stage"]["inputs"] == [
        "mdocean/plots/non_matlab_figs/taxonomy.mmd"
    ]
    assert payload["stage"]["stage"]["outputs"] == [
        {
            "path": "mdocean/plots/non_matlab_figs/taxonomy.pdf",
            "storage": "dvc",
        }
    ]


def test_xr_json_run_mode(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "--json",
            "--environment",
            "_system",
            "true",
        ],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "run"
    assert payload["execution"]["status"] == "completed"
    assert payload["execution"]["error"] is None
    assert payload["stage"]["stage"]["kind"] == "shell-command"
    assert payload["stage"]["stage"]["command"] == "true"


def test_xr_non_allowlisted_docker_command_dry_run(tmp_dir):
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "--dry-run",
            "--json",
            "--",
            (
                "docker run --rm -it -v $PWD:/work "
                "ghcr.io/turbinesfoam/turbinesfoam blockMesh"
            ),
        ],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["environment"]["name"] == "turbinesfoam"
    assert payload["environment"]["exists"] is False
    assert payload["environment"]["env"] == {
        "kind": "docker",
        "image": "ghcr.io/turbinesfoam/turbinesfoam:latest",
        "description": (
            "Docker CLI via image ghcr.io/turbinesfoam/turbinesfoam:latest."
        ),
        "wdir": "/work",
        "command_mode": "shell",
    }
    assert payload["stage"]["stage"]["kind"] == "shell-command"
    assert payload["stage"]["stage"]["command"] == "blockMesh"


def test_xr_non_allowlisted_docker_run_stays_shell_command(
    tmp_dir,
):
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "--dry-run",
            "--json",
            "--",
            "docker run -it ubuntu cp myfile otherfile",
        ],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["stage"]["stage"]["kind"] == "shell-command"
    assert payload["stage"]["stage"]["command"] == "cp myfile otherfile"
    stage = payload["stage"]["stage"]
    assert stage["inputs"] == ["myfile"]
    assert stage["outputs"] == [{"path": "otherfile", "storage": "git"}]


def test_xr_julia_script(tmp_dir):
    """Test xr command with Julia script in dry-run JSON mode."""
    subprocess.check_call(["calkit", "init"])
    # Create a Julia script that uses CSV to read/write
    with open("analyze.jl", "w") as f:
        f.write("""
using CSV
using DataFrames

# Read input CSV
data = CSV.read("input.csv", DataFrame)

# Process: add a new column with doubled values
data.doubled = data.value .* 2

# Write output CSV
CSV.write("output.csv", data)

println("Analysis complete")
""")
    # Create input CSV file
    with open("input.csv", "w") as f:
        f.write("id,value\n1,10\n2,20\n3,30\n")
    # Dry-run should infer environment and stage metadata without execution
    result = subprocess.run(
        ["calkit", "xr", "--dry-run", "--json", "analyze.jl"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Dry-run command failed: {result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["environment"]["created_from_dependencies"] is True
    assert payload["environment"]["env"]["kind"] == "julia"
    assert payload["environment"]["spec_path"] == "Project.toml"
    assert "CSV" in payload["environment"]["dependencies"]
    assert "DataFrames" in payload["environment"]["dependencies"]
    assert payload["stage"]["name"] == "analyze"
    assert payload["stage"]["stage"]["kind"] == "julia-script"
    assert payload["stage"]["stage"]["script_path"] == "analyze.jl"
    assert "input.csv" in payload["stage"]["stage"].get("inputs", [])
    assert {"path": "output.csv", "storage": "git"} in payload["stage"][
        "stage"
    ].get("outputs", [])
    # Dry-run should not execute the script or materialize env files
    assert not os.path.exists("output.csv")
    assert not os.path.exists("Project.toml")


def test_xr_r_script(tmp_dir):
    """Test xr command with R script in dry-run JSON mode."""
    subprocess.check_call(["calkit", "init"])
    # Create an R script with library dependencies for auto-detection
    with open("analyze.R", "w") as f:
        f.write("""
library(readr)
library(dplyr)

# Read input
data <- read_csv("input.csv")

# Process data
result <- data %>%
  summarise(mean_value = mean(value))

# Write output
write_csv(result, "output.csv")

cat("Analysis complete\\n")
""")
    # Create input file
    with open("input.csv", "w") as f:
        f.write("value\n1\n2\n3\n")
    # Dry-run should infer environment and stage metadata without execution
    result = subprocess.run(
        ["calkit", "xr", "--dry-run", "--json", "analyze.R"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0, f"Dry-run command failed: {result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["environment"]["created_from_dependencies"] is True
    assert payload["environment"]["env"]["kind"] == "renv"
    assert payload["environment"]["spec_path"] == "DESCRIPTION"
    assert "readr" in payload["environment"]["dependencies"]
    assert "dplyr" in payload["environment"]["dependencies"]
    assert payload["stage"]["name"] == "analyze"
    assert payload["stage"]["stage"]["kind"] == "r-script"
    assert payload["stage"]["stage"]["script_path"] == "analyze.R"
    assert "input.csv" in payload["stage"]["stage"].get("inputs", [])
    outputs = payload["stage"]["stage"].get("outputs", [])
    output_paths = [
        out["path"] if isinstance(out, dict) else out for out in outputs
    ]
    assert "output.csv" in output_paths
    # Dry-run should not execute the script or materialize env files
    assert not os.path.exists("output.csv")
    assert not os.path.exists("DESCRIPTION")


@pytest.mark.skipif(
    shutil.which("matlab") is None, reason="MATLAB not installed"
)
def test_xr_matlab_script(tmp_dir):
    from scipy.io import savemat

    # Create a dependency MATLAB function
    os.makedirs("src", exist_ok=True)
    with open("src/myfunction.m", "w") as f:
        f.write(
            """
function out = myfunction(x)
out = x * 2;
end
"""
        )
    # Create a MATLAB script
    with open("compute.m", "w") as f:
        f.write("""
addpath(genpath('src'));
result = myfunction(1);
data = load('input.mat');
result = data.value * 2 + result;
save('output.mat', 'result');
disp('Computation complete');
parquetwrite("data.parquet", table(rand(1000, 1)));
""")
    # Create input file
    savemat("input.mat", {"value": 42})
    # Execute and record
    result = subprocess.run(
        ["calkit", "xr", "compute.m"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    # Verify stage was added
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "compute" in stages
    stage = stages["compute"]
    assert stage["kind"] == "matlab-script"
    assert stage["script_path"] == "compute.m"
    assert stage["environment"] == "_system"
    assert "input.mat" in stage["inputs"]
    assert {"path": "data.parquet", "storage": "dvc"} in stage["outputs"]
    assert "src/myfunction.m" in stage["inputs"]
    assert "compute.m" not in stage["inputs"]


def test_xr_with_user_inputs_outputs(tmp_dir):
    """Test xr command with user-specified inputs and outputs."""
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py-env",
            "--python",
            "3.12",
            "numpy",
        ]
    )
    # Create a script
    with open("calc.py", "w") as f:
        f.write("""
import numpy as np

# This won't be detected automatically
arr = np.array([1, 2, 3])
np.save('data.npy', arr)
""")
    # Create the input file that we'll reference
    with open("config.txt", "w") as f:
        f.write("test config")
    # Execute with explicit inputs/outputs
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "calc.py",
            "-e",
            "py-env",
            "--input",
            "config.txt",
            "--output",
            "data.npy",
        ],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    # Verify inputs/outputs
    ck_info = calkit.load_calkit_info()
    stage = ck_info["pipeline"]["stages"]["calc"]
    assert "config.txt" in stage["inputs"]
    # Find the data.npy output
    outputs = stage["outputs"]
    assert any(
        out["path"] == "data.npy"
        if isinstance(out, dict)
        else out == "data.npy"
        for out in outputs
    )


def test_xr_failure_rollback(tmp_dir):
    """Test that xr rolls back pipeline changes if execution fails."""
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py-env",
            "--python",
            "3.12",
            "setuptools",
        ]
    )
    # Create a failing script
    with open("fail.py", "w") as f:
        f.write("""
raise RuntimeError("Intentional failure")
""")
    # Execute and expect failure
    result = subprocess.run(
        ["calkit", "xr", "fail.py", "-e", "py-env"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode != 0
    # Verify stage was NOT added to pipeline
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "fail" not in stages


def test_xr_no_io_detect(tmp_dir):
    """Test xr command with I/O detection disabled."""
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py-env",
            "--python",
            "3.12",
            "setuptools",
        ]
    )
    # Create a script with I/O
    with open("script.py", "w") as f:
        f.write("""
with open('input.txt', 'r') as f:
    data = f.read()
with open('output.txt', 'w') as f:
    f.write(data)
""")
    with open("input.txt", "w") as f:
        f.write("test")
    # Execute with detection disabled
    result = subprocess.run(
        ["calkit", "xr", "script.py", "-e", "py-env", "--no-detect-io"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    # Verify no automatic I/O was detected (inputs will be empty)
    ck_info = calkit.load_calkit_info()
    stage = ck_info["pipeline"]["stages"]["script"]
    # With --no-detect-io, no inputs should be detected (not even the script)
    assert len(stage.get("inputs", [])) == 0


def test_xr_stage_name_conflict(tmp_dir):
    """Test that xr auto-increments stage names on conflict."""
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py-env",
            "--python",
            "3.12",
            "setuptools",
        ]
    )
    # Create two different scripts with the same base name
    with open("process.py", "w") as f:
        f.write("print('Version 1')")
    # Execute and record the first version
    result = subprocess.run(
        ["calkit", "xr", "process.py", "-e", "py-env"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # Now create a different script with a different path but same name
    os.mkdir("scripts")
    with open("scripts/process.py", "w") as f:
        f.write("print('Version 2')")
    # Try to execute the second version without specifying a stage name
    # Should auto-increment to "process-2"
    result = subprocess.run(
        ["calkit", "xr", "scripts/process.py", "-e", "py-env"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    # Should succeed with auto-incremented name
    assert result.returncode == 0
    assert "using 'process-2' instead" in result.stdout
    # Verify the stage was created with the incremented name
    ck_info = calkit.load_calkit_info()
    assert "process" in ck_info["pipeline"]["stages"]
    assert "process-2" in ck_info["pipeline"]["stages"]
    assert (
        ck_info["pipeline"]["stages"]["process"]["script_path"] == "process.py"
    )
    assert (
        ck_info["pipeline"]["stages"]["process-2"]["script_path"]
        == "scripts/process.py"
    )
    # Verify we can still add with an explicit stage name
    os.makedirs("other", exist_ok=True)
    with open("other/process.py", "w") as f:
        f.write("print('Version 3')")
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "other/process.py",
            "-e",
            "py-env",
            "--stage",
            "process-v3",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # Verify all three stages exist
    ck_info = calkit.load_calkit_info()
    stages = ck_info["pipeline"]["stages"]
    assert "process" in stages
    assert "process-2" in stages
    assert "process-v3" in stages
    assert stages["process"]["script_path"] == "process.py"
    assert stages["process-2"]["script_path"] == "scripts/process.py"
    assert stages["process-v3"]["script_path"] == "other/process.py"


def test_xr_jupyter_notebook_conda_env(tmp_dir):
    # First, create a conda env with matplotlib and jupyter deps
    os.makedirs("env")
    env_path = "env/environment.yml"
    with open(env_path, "w") as f:
        f.write("name: test-env\n")
        f.write("channels:\n")
        f.write("  - conda-forge\n")
        f.write("dependencies:\n")
        f.write("  - python=3.11\n")
        f.write("  - pandas\n")
        f.write("  - matplotlib\n")
        f.write("  - jupyter\n")
    os.makedirs("src")
    notebook_path = "src/process_data.ipynb"
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import pandas as pd\n",
                    "import numpy as np\n",
                    "import matplotlib.pyplot as plt\n",
                ],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "python",
                "name": "python3",
            }
        },
    }
    with open(notebook_path, "w") as f:
        json.dump(notebook, f)
    subprocess.check_call(["calkit", "init"])
    # Execute in dry run mode and check the output
    # We should create a "main" environment with kind conda and path `env_path`
    result = subprocess.run(
        ["calkit", "xr", notebook_path, "-d"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    assert "kind: conda" in result.stdout
    assert f"path: {env_path}" in result.stdout
