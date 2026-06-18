"""Tests for the ``calkit.detect`` module."""

import json
import os

import pytest

from calkit.detect import (
    create_julia_project_file,
    create_python_requirements_file,
    create_r_description_file,
    detect_dependencies_from_notebook,
    detect_io,
    detect_julia_dependencies,
    detect_julia_script_io,
    detect_jupyter_notebook_io,
    detect_latex_io,
    detect_python_dependencies,
    detect_python_script_io,
    detect_r_dependencies,
    detect_r_script_io,
    detect_shell_command_io,
    detect_shell_script_io,
    generate_stage_name,
)


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """Fixture to change to a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_detect_python_script_io(tmp_dir):
    """Test detection of inputs and outputs from Python scripts."""
    # Create a Python script with various file operations
    script_content = """
import numpy as np
import pandas as pd
from mymodule import helper

# Read operations
with open('input.txt', 'r') as f:
    data = f.read()

df = pd.read_csv('data.csv')
arr = np.load('array.npy')

# Write operations
with open('output.txt', 'w') as f:
    f.write(data)

df.to_csv('result.csv')
np.save('output.npy', arr)

import matplotlib.pyplot as plt
plt.savefig('plot.png')
"""
    with open("script.py", "w") as f:
        f.write(script_content)
    # Create a local module to test import detection
    with open("mymodule.py", "w") as f:
        f.write("def helper(): pass")
    result = detect_python_script_io("script.py")
    # Check detected inputs
    assert "input.txt" in result["inputs"]
    assert "data.csv" in result["inputs"]
    assert "array.npy" in result["inputs"]
    assert "mymodule.py" in result["inputs"]
    # Check detected outputs
    assert "output.txt" in result["outputs"]
    assert "result.csv" in result["outputs"]
    assert "output.npy" in result["outputs"]
    assert "plot.png" in result["outputs"]


def test_detect_python_script_io_with_modes(tmp_dir):
    """Test Python script detection with different file modes."""
    script_content = """
# Append mode
with open('log.txt', 'a') as f:
    f.write('log')

# Read mode (default)
with open('config.txt') as f:
    config = f.read()

# Explicit read mode
with open('data.txt', mode='r') as f:
    data = f.read()
"""
    with open("script.py", "w") as f:
        f.write(script_content)
    result = detect_python_script_io("script.py")
    assert "log.txt" in result["outputs"]  # append is an output
    assert "config.txt" in result["inputs"]
    assert "data.txt" in result["inputs"]


def test_detect_python_script_io_in_subdir_uses_cwd(tmp_dir):
    """Ensure script I/O is resolved relative to the working directory."""
    os.makedirs("scripts", exist_ok=True)
    script_content = """
with open('output.txt', 'w') as f:
    f.write('done')
"""
    with open("scripts/run.py", "w") as f:
        f.write(script_content)
    result = detect_python_script_io("scripts/run.py")
    assert "output.txt" in result["outputs"]
    assert "scripts/output.txt" not in result["outputs"]


def test_detect_julia_script_io(tmp_dir):
    """Test detection of inputs and outputs from Julia scripts."""
    script_content = """
include("utils.jl")

using CSV
using DataFrames

# Read operations
data = CSV.read("input.csv", DataFrame)
arr = readdlm("matrix.txt")
f = open("config.txt", "r")

# Write operations
CSV.write("output.csv", df)
writedlm("result.txt", matrix)
open("log.txt", "w") do f
    write(f, "log")
end
"""
    with open("script.jl", "w") as f:
        f.write(script_content)
    # Create the included file
    with open("utils.jl", "w") as f:
        f.write("# utilities")
    result = detect_julia_script_io("script.jl")
    # Check detected inputs
    assert "utils.jl" in result["inputs"]
    assert "input.csv" in result["inputs"]
    assert "matrix.txt" in result["inputs"]
    assert "config.txt" in result["inputs"]
    # Check detected outputs
    assert "output.csv" in result["outputs"]
    assert "result.txt" in result["outputs"]
    assert "log.txt" in result["outputs"]


def test_detect_julia_script_io_with_const_paths(tmp_dir):
    """Test detection when Julia scripts use const path variables."""
    script_content = """
using CSV
using DataFrames

const INPUT_PATH = "data/raw.csv"
const OUTPUT_PATH = "data/processed.csv"

df = CSV.read(INPUT_PATH, DataFrame)
CSV.write(OUTPUT_PATH, df)
"""
    with open("script.jl", "w") as f:
        f.write(script_content)
    result = detect_julia_script_io("script.jl")
    assert "data/raw.csv" in result["inputs"]
    assert "data/processed.csv" in result["outputs"]


def test_detect_r_script_io(tmp_dir):
    """Test detection of inputs and outputs from R scripts."""
    script_content = """
source("utils.R")

library(readr)
library(ggplot2)

# Read operations
data <- read.csv("input.csv")
rds_data <- readRDS("data.rds")
load("workspace.RData")
excel_data <- read_excel("data.xlsx")

# Write operations
write.csv(result, "output.csv")
saveRDS(model, "model.rds")
save(data, result, file="output.RData")
ggsave("plot.png")
write_csv(data, "clean_data.csv")
pdf("figure.pdf")
"""
    with open("script.R", "w") as f:
        f.write(script_content)
    # Create the sourced file
    with open("utils.R", "w") as f:
        f.write("# utilities")
    result = detect_r_script_io("script.R")
    # Check detected inputs
    assert "utils.R" in result["inputs"]
    assert "input.csv" in result["inputs"]
    assert "data.rds" in result["inputs"]
    assert "workspace.RData" in result["inputs"]
    assert "data.xlsx" in result["inputs"]
    # Check detected outputs
    assert "output.csv" in result["outputs"]
    assert "model.rds" in result["outputs"]
    assert "output.RData" in result["outputs"]
    assert "plot.png" in result["outputs"]
    assert "clean_data.csv" in result["outputs"]
    assert "figure.pdf" in result["outputs"]
    # An orchestrator script that sources other scripts via here::here()
    # should recursively attribute their I/O to the stage
    os.makedirs("code", exist_ok=True)
    master_content = """
here::i_am("code/master.R")
log_file <- here::here("output", "run.log")
sink(log_file, split = TRUE)
source(here::here("code", "clean.R"))
source(here::here("code", "model.R"))
sink()
"""
    clean_content = """
raw <- read_excel("data/raw.xlsx", sheet = "Master")
saveRDS(raw, file = "data/clean.rds")
"""
    model_content = """
df <- readRDS("data/clean.rds")
write.csv(df, file = "output/tables/summary.csv")
ggsave("output/figures/plot.pdf", p)
sink("output/tables/model.tex")
"""
    with open("code/master.R", "w") as f:
        f.write(master_content)
    with open("code/clean.R", "w") as f:
        f.write(clean_content)
    with open("code/model.R", "w") as f:
        f.write(model_content)
    master = detect_r_script_io("code/master.R")
    # Sourced scripts are detected as inputs even when wrapped in here::here()
    assert "code/clean.R" in master["inputs"]
    assert "code/model.R" in master["inputs"]
    # I/O from sourced scripts is attributed to the orchestrator
    assert "data/raw.xlsx" in master["inputs"]
    # Named file=/filename= write arguments are detected
    assert "data/clean.rds" in master["outputs"]
    assert "output/tables/summary.csv" in master["outputs"]
    # sink(), here::here()-assigned variables, and ggsave() literals
    assert "output/run.log" in master["outputs"]
    assert "output/tables/model.tex" in master["outputs"]
    assert "output/figures/plot.pdf" in master["outputs"]
    # An intermediate produced and consumed within the stage is not an input
    assert "data/clean.rds" not in master["inputs"]


def test_detect_shell_script_io(tmp_dir):
    """Test detection of inputs and outputs from shell scripts."""
    script_content = """#!/bin/bash
# Read operations
cat input.txt
head -n 10 data.csv
grep "pattern" config.txt

# Write operations
echo "hello" > output.txt
cat file1.txt file2.txt >> combined.txt
cp source.txt dest.txt
"""
    with open("script.sh", "w") as f:
        f.write(script_content)
    result = detect_shell_script_io("script.sh")
    # Check detected inputs
    assert "input.txt" in result["inputs"]
    assert "data.csv" in result["inputs"]
    assert "config.txt" in result["inputs"]
    # Check detected outputs
    assert "output.txt" in result["outputs"]
    assert "combined.txt" in result["outputs"]
    assert "dest.txt" in result["outputs"]


def test_detect_jupyter_notebook_io_python(tmp_dir):
    """Test detection of inputs and outputs from Python Jupyter notebooks.

    Covers:
    - Basic file I/O operations (open, pandas read/write)
    - Chained method calls like ax.get_figure().savefig()
    - Relative path resolution with directory changes
    - Matplotlib savefig detection (both plt.savefig and fig.savefig)
    - Jupyter %cd magic command for changing directories
    """
    # Test 1: Basic I/O with subdirectory and chained methods
    os.makedirs("notebooks", exist_ok=True)
    notebook_basic = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import pandas as pd\n",
                    "from helper import process\n",
                    "import matplotlib.pyplot as plt\n",
                    "import seaborn as sns\n",
                    "import os\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "df = pd.read_csv('data.csv')\n",
                    "with open('input.txt', 'r') as f:\n",
                    "    text = f.read()\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "df.to_csv('output.csv')\n",
                    "with open('result.txt', 'w') as f:\n",
                    "    f.write(text)\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "sns.set_theme()\n",
                    "ax = df.plot()\n",
                    "ax.get_figure().savefig('../figures/plot.png')\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "x = [1, 2, 3]\n",
                    "y = [1, 4, 9]\n",
                    "plt.plot(x, y)\n",
                    "plt.savefig('basic_plot.png')\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "fig, ax = plt.subplots()\n",
                    "ax.plot(x, y)\n",
                    "fig.savefig('figure_plot.pdf')\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {
                "language": "python",
                "name": "python3",
            }
        },
    }
    with open("notebooks/notebook.ipynb", "w") as f:
        json.dump(notebook_basic, f)
    with open("notebooks/helper.py", "w") as f:
        f.write("def process(): pass")
    result = detect_jupyter_notebook_io("notebooks/notebook.ipynb")
    # Basic file I/O
    assert "notebooks/data.csv" in result["inputs"]
    assert "notebooks/input.txt" in result["inputs"]
    assert "notebooks/helper.py" in result["inputs"]
    assert "notebooks/output.csv" in result["outputs"]
    assert "notebooks/result.txt" in result["outputs"]
    # Chained method calls and relative paths
    assert "figures/plot.png" in result["outputs"]
    # Matplotlib savefig
    assert "notebooks/basic_plot.png" in result["outputs"]
    assert "notebooks/figure_plot.pdf" in result["outputs"]
    # Test 2: %cd magic command for changing directories
    os.makedirs("data", exist_ok=True)
    os.makedirs("output", exist_ok=True)
    notebook_cd = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import pandas as pd\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "%cd data\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "df = pd.read_csv('input.csv')\n",
                    "df.to_csv('../output/result.csv')\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {
                "language": "python",
                "name": "python3",
            }
        },
    }
    with open("notebook_cd.ipynb", "w") as f:
        json.dump(notebook_cd, f)
    result_cd = detect_jupyter_notebook_io("notebook_cd.ipynb")
    # File read after %cd data should be detected as data/input.csv
    assert "data/input.csv" in result_cd["inputs"]
    # File written after %cd data with ../ path should be detected as
    # output/result.csv
    assert "output/result.csv" in result_cd["outputs"]


def test_detect_jupyter_notebook_io_with_variables(tmp_dir):
    """Test detection of I/O when file paths are stored in variables."""
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import os\n",
                    "import pandas as pd\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "log_path_template = '../.calkit/scheduler/logs/amip-{case}.out'\n",
                    "data_file = 'input_data.csv'\n",
                    "output_dir = 'results'\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "# Reading from variable\n",
                    "with open(log_path_template.format(case='baseline')) as f:\n",
                    "    log_data = f.read()\n",
                    "# Reading with direct variable\n",
                    "df = pd.read_csv(data_file)\n",
                    "# Writing with variable\n",
                    "df.to_csv(output_dir + '/results.csv')\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {
                "language": "python",
                "name": "python3",
            }
        },
    }
    with open("notebook_vars.ipynb", "w") as f:
        json.dump(notebook, f)
    result = detect_jupyter_notebook_io("notebook_vars.ipynb")
    # Variable references should be resolved
    assert "input_data.csv" in result["inputs"]
    # Template string from format should be detected
    assert ".calkit/scheduler/logs/amip-baseline.out" in result["inputs"]


def test_detect_jupyter_notebook_io_julia(tmp_dir):
    """Test detection of inputs and outputs from Julia Jupyter notebooks."""
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    'include("utils.jl")\n',
                    "using CSV\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    'data = CSV.read("input.csv", DataFrame)\n',
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    'CSV.write("output.csv", processed)\n',
                ],
            },
        ],
        "metadata": {
            "kernelspec": {
                "language": "julia",
                "name": "julia-1.9",
            }
        },
    }
    with open("notebook.ipynb", "w") as f:
        json.dump(notebook, f)
    # Create the included file
    with open("utils.jl", "w") as f:
        f.write("# utilities")
    result = detect_jupyter_notebook_io("notebook.ipynb")
    # Check detected inputs
    assert "utils.jl" in result["inputs"]
    assert "input.csv" in result["inputs"]
    # Check detected outputs
    assert "output.csv" in result["outputs"]


def test_detect_latex_io_fallback(tmp_dir):
    """Test detection of inputs from LaTeX files (fallback mode)."""
    latex_content = r"""
\documentclass{article}
\input{preamble}
\include{introduction}

\begin{document}
\includegraphics{figure.png}
\includegraphics[width=0.5\textwidth]{plot.pdf}
\bibliography{refs}
\end{document}
"""
    with open("paper.tex", "w") as f:
        f.write(latex_content)
    # Test without environment (will use fallback)
    result = detect_latex_io("paper.tex")
    # Check detected inputs
    assert "preamble.tex" in result["inputs"]
    assert "introduction.tex" in result["inputs"]
    assert "figure.png" in result["inputs"]
    assert "plot.pdf" in result["inputs"]
    assert "refs.bib" in result["inputs"]
    # Check that outputs are empty (handled by LatexStage)
    assert result["outputs"] == []


def test_detect_latex_io_in_subfolder(tmp_dir):
    """Test detection of LaTeX inputs when document is in a subfolder."""
    # Create a subfolder structure
    os.makedirs("paper", exist_ok=True)
    # Create LaTeX document in subfolder
    latex_content = r"""
\documentclass{article}
\input{preamble}
\input{chapters/intro}
\includegraphics{figures/diagram.png}
\bibliography{refs}
\end{document}
"""
    with open("paper/main.tex", "w") as f:
        f.write(latex_content)
    # Create the referenced files
    with open("paper/preamble.tex", "w") as f:
        f.write(r"\usepackage{graphicx}" + "\n")
    os.makedirs("paper/chapters", exist_ok=True)
    with open("paper/chapters/intro.tex", "w") as f:
        f.write(r"\section{Introduction}" + "\n")
    os.makedirs("paper/figures", exist_ok=True)
    with open("paper/figures/diagram.png", "w") as f:
        f.write("PNG content")
    with open("paper/refs.bib", "w") as f:
        f.write("@article{test, title={Test}}\n")
    # Test detection - paths should be relative to project root
    result = detect_latex_io("paper/main.tex")
    # Check detected inputs
    assert "paper/preamble.tex" in result["inputs"]
    assert "paper/chapters/intro.tex" in result["inputs"]
    assert "paper/figures/diagram.png" in result["inputs"]
    assert "paper/refs.bib" in result["inputs"]
    # Check that outputs are empty (handled by LatexStage)
    assert result["outputs"] == []


def test_detect_shell_command_io(tmp_dir):
    """Test detection of inputs and outputs from shell commands."""
    # Test input redirection
    result = detect_shell_command_io("sort < input.txt")
    assert "input.txt" in result["inputs"]
    # Test output redirection
    result = detect_shell_command_io("echo hello > output.txt")
    assert "output.txt" in result["outputs"]
    # Test append redirection
    result = detect_shell_command_io("echo world >> log.txt")
    assert "log.txt" in result["outputs"]
    # Test cat command
    result = detect_shell_command_io("cat data.csv")
    assert "data.csv" in result["inputs"]
    # Test complex command
    result = detect_shell_command_io("grep pattern input.txt > matches.txt")
    assert "input.txt" in result["inputs"]
    assert "matches.txt" in result["outputs"]


def test_detect_python_script_io_relative_imports(tmp_dir):
    """Test detection of relative imports in Python scripts."""
    # Create a package structure
    os.makedirs("mypackage")
    with open("mypackage/__init__.py", "w") as f:
        f.write("")
    with open("mypackage/submodule.py", "w") as f:
        f.write("def func(): pass")
    # Create a script with relative imports
    script_content = """
from . import submodule
from .submodule import func
"""
    with open("mypackage/main.py", "w") as f:
        f.write(script_content)
    result = detect_python_script_io("mypackage/main.py")
    # Note: relative imports detection depends on the directory context
    # The function may return __init__.py or submodule.py
    # Just verify no errors occur
    assert isinstance(result["inputs"], list)
    assert isinstance(result["outputs"], list)


def test_detect_python_script_nonexistent_file(tmp_dir):
    """Test that detect functions handle nonexistent files gracefully."""
    result = detect_python_script_io("nonexistent.py")
    assert result["inputs"] == []
    assert result["outputs"] == []


def test_detect_julia_script_nonexistent_file(tmp_dir):
    """Test that Julia detection handles nonexistent files gracefully."""
    result = detect_julia_script_io("nonexistent.jl")
    assert result["inputs"] == []
    assert result["outputs"] == []


def test_detect_notebook_nonexistent_file(tmp_dir):
    """Test that notebook detection handles nonexistent files gracefully."""
    result = detect_jupyter_notebook_io("nonexistent.ipynb")
    assert result["inputs"] == []
    assert result["outputs"] == []


def test_generate_stage_name():
    """Test stage name generation from commands."""
    # Test Python script without args
    name = generate_stage_name(["process.py"])
    assert name == "process"
    # Test Python script with args - args are no longer included
    name = generate_stage_name(["process.py", "--verbose", "input.txt"])
    assert name == "process"
    # Test python interpreter with script
    name = generate_stage_name(["python", "process.py"])
    assert name == "process"
    # Test python interpreter with script and args
    name = generate_stage_name(
        ["python", "scripts/process_data.py", "--verbose"]
    )
    assert name == "process-data"
    # Test Julia script
    name = generate_stage_name(["analyze.jl"])
    assert name == "analyze"
    # Test julia interpreter with script
    name = generate_stage_name(["julia", "analyze.jl"])
    assert name == "analyze"
    # Test MATLAB script
    name = generate_stage_name(["run_simulation.m"])
    assert name == "run-simulation"
    # Test matlab interpreter with script
    name = generate_stage_name(["matlab", "run_simulation.m"])
    assert name == "run-simulation"
    # Test notebook
    name = generate_stage_name(["notebooks/analysis.ipynb"])
    assert name == "analysis-notebook"
    # Test shell script - args are no longer included
    name = generate_stage_name(["build.sh", "production"])
    assert name == "build"
    # Test LaTeX document
    name = generate_stage_name(["paper.tex"])
    assert name == "paper"
    # Test with path (should use basename)
    name = generate_stage_name(["scripts/process_data.py"])
    assert name == "process-data"
    # Test underscore to dash conversion
    name = generate_stage_name(["my_script.py"])
    assert name == "my-script"
    # Test shell command (returns command name with args)
    name = generate_stage_name(["echo", "Hello", "World"])
    assert name == "echo-hello-world"
    # Test matlab command with parentheses (should be removed) and -batch
    # (should be removed)
    name = generate_stage_name(["matlab", "-batch", "disp('test')"])
    assert name == "matlab-disptest"
    # Test matlab command with -batch and other flags
    name = generate_stage_name(["matlab", "-batch", "run_script"])
    assert name == "matlab-run-script"
    # Test empty command
    name = generate_stage_name([])
    assert name == "stage"
    # Test script with options - args are no longer included
    name = generate_stage_name(["script.py", "--flag1", "--flag2"])
    assert name == "script"
    # Test with dots in filename (should be converted to dashes)
    name = generate_stage_name(["data.process.py"])
    assert name == "data-process"
    # Test with dots and underscores
    name = generate_stage_name(["my_data.processor.py"])
    assert name == "my-data-processor"


def test_detect_io(tmp_dir):
    """Test the detect_io function with different stage types."""
    # Test Python script stage
    python_script = """
with open('input.txt', 'r') as f:
    data = f.read()
with open('output.txt', 'w') as f:
    f.write(data)
"""
    with open("process.py", "w") as f:
        f.write(python_script)
    stage = {
        "kind": "python-script",
        "script_path": "process.py",
        "environment": "py",
    }
    result = detect_io(stage)
    assert "input.txt" in result["inputs"]
    assert "output.txt" in result["outputs"]
    # Test shell command stage
    stage = {
        "kind": "shell-command",
        "command": "cat input.dat > output.dat",
        "environment": "_system",
    }
    result = detect_io(stage)
    assert "input.dat" in result["inputs"]
    assert "output.dat" in result["outputs"]
    stage = {
        "kind": "shell-command",
        "command": "cp myfile otherfile",
        "environment": "_system",
    }
    result = detect_io(stage)
    assert result["inputs"] == ["myfile"]
    assert result["outputs"] == ["otherfile"]
    # Test LaTeX stage
    latex_content = r"""
\documentclass{article}
\input{preamble}
\includegraphics{figure.png}
\end{document}
"""
    with open("paper.tex", "w") as f:
        f.write(latex_content)
    stage = {
        "kind": "latex",
        "target_path": "paper.tex",
        "environment": "latex",
    }
    result = detect_io(stage)
    assert "preamble.tex" in result["inputs"]
    assert "figure.png" in result["inputs"]
    # Test Julia script stage
    julia_script = """
data = readdlm("data.csv")
writedlm("result.csv", data)
"""
    with open("analyze.jl", "w") as f:
        f.write(julia_script)
    stage = {
        "kind": "julia-script",
        "script_path": "analyze.jl",
        "environment": "julia",
    }
    result = detect_io(stage)
    assert "data.csv" in result["inputs"]
    assert "result.csv" in result["outputs"]
    # Test unsupported stage kind (should return empty)
    stage = {
        "kind": "unknown-stage-type",
        "environment": "test",
    }
    result = detect_io(stage)
    assert result["inputs"] == []
    assert result["outputs"] == []
    # Test notebook stage
    notebook_content = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import pandas as pd\n",
                    "df = pd.read_csv('data.csv')\n",
                    "df.to_csv('output.csv')",
                ],
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 4,
    }
    with open("analysis.ipynb", "w") as f:
        json.dump(notebook_content, f)
    stage = {
        "kind": "jupyter-notebook",
        "notebook_path": "analysis.ipynb",
        "environment": "py",
    }
    result = detect_io(stage)
    assert "data.csv" in result["inputs"]
    assert "output.csv" in result["outputs"]


# Dependency detection tests


def test_detect_python_dependencies_from_script(tmp_dir):
    """Test detection of Python dependencies from a script."""
    script_content = """
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
import matplotlib.pyplot as plt
import os  # stdlib
import sys  # stdlib

data = pd.read_csv("data.csv")
"""
    with open("script.py", "w") as f:
        f.write(script_content)
    deps = detect_python_dependencies(script_path="script.py")
    assert "numpy" in deps
    assert "pandas" in deps
    assert "sklearn" in deps
    assert "matplotlib" in deps
    # stdlib modules should not be included
    assert "os" not in deps
    assert "sys" not in deps


def test_detect_python_dependencies_from_code():
    """Test detection of Python dependencies from code string."""
    code = """
import requests
from flask import Flask
import json  # stdlib
"""
    deps = detect_python_dependencies(code=code)
    assert "requests" in deps
    assert "flask" in deps
    assert "json" not in deps


def test_detect_r_dependencies_from_script(tmp_dir):
    """Test detection of R dependencies from a script."""
    script_content = """
library(ggplot2)
require(dplyr)
library("tidyr")

# This should not be detected (base package)
library(base)

data <- read.csv("data.csv")
"""
    with open("script.R", "w") as f:
        f.write(script_content)

    deps = detect_r_dependencies(script_path="script.R")

    assert "ggplot2" in deps
    assert "dplyr" in deps
    assert "tidyr" in deps
    # Base packages should not be included
    assert "base" not in deps
    # Qualified calls (pkg::fn), requireNamespace/loadNamespace, and
    # pacman::p_load with a character vector should all be detected
    pacman_content = """
if (!requireNamespace("here", quietly = TRUE)) install.packages("here")
here::i_am("code/master.R")
loadNamespace("withr")
pkgs <- c(
  "haven", "readxl",
  "dplyr", "ggplot2"
)
pacman::p_load(char = pkgs, install = TRUE, character.only = TRUE)
pacman::p_load(stringr, tidyr)
pacman::p_load("forcats", c("janitor", "lubridate"))
"""
    deps = detect_r_dependencies(code=pacman_content)
    # Qualified call and the requireNamespace/loadNamespace guards
    assert "here" in deps
    assert "pacman" in deps
    assert "withr" in deps
    # Vector resolved via char =
    assert "haven" in deps
    assert "readxl" in deps
    assert "ggplot2" in deps
    # Bare non-standard-evaluation names
    assert "stringr" in deps
    assert "tidyr" in deps
    # Quoted names and inline c() vectors
    assert "forcats" in deps
    assert "janitor" in deps
    assert "lubridate" in deps
    # The vector constructor and keyword-argument values are not packages
    assert "c" not in deps
    assert "TRUE" not in deps
    assert "install" not in deps
    assert "character.only" not in deps


def test_detect_r_dependencies_from_code():
    """Test detection of R dependencies from code string."""
    code = """
library(readr)
require(data.table)
"""
    deps = detect_r_dependencies(code=code)

    assert "readr" in deps
    assert "data.table" in deps


def test_detect_julia_dependencies_from_script(tmp_dir):
    """Test detection of Julia dependencies from a script."""
    script_content = """
using DataFrames
using CSV
using Plots

# Read data
data = CSV.read("data.csv", DataFrame)
"""
    with open("script.jl", "w") as f:
        f.write(script_content)

    deps = detect_julia_dependencies(script_path="script.jl")

    assert "DataFrames" in deps
    assert "CSV" in deps
    assert "Plots" in deps


def test_detect_julia_dependencies_from_code():
    """Test detection of Julia dependencies from code string."""
    code = """
using LinearAlgebra
using Statistics
"""
    deps = detect_julia_dependencies(code=code)

    assert "LinearAlgebra" in deps
    assert "Statistics" in deps


def test_detect_dependencies_from_python_notebook(tmp_dir):
    """Test detection of dependencies from a Python Jupyter notebook.

    Tests both basic imports and IPython magic commands (line and cell magics).
    """
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import numpy as np\n",
                    "import pandas as pd\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "from sklearn.linear_model import LinearRegression\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "import matplotlib.pyplot as plt\n",
                    "\n",
                    "%matplotlib inline\n",
                    "\n",
                    "class Constants():\n",
                    "    def __init__(self):\n",
                    "        self.msun = 1.989e33\n",
                    "        self.rsun = 6.955e10\n",
                    "        self.G  = 6.674e-8\n",
                    "        self.yr = 3.1536e7\n",
                    "        self.h  = 6.6260755e-27\n",
                    "        self.kB = 1.380658e-16\n",
                    "        self.mp = 1.6726219e-24\n",
                    "        self.me = 9.10938356e-28\n",
                    "        self.c  = 2.99792458e10\n",
                    "        self.pc = 3.085677581e18\n",
                    "        self.au = 1.496e13\n",
                    "        self.q = 4.8032068e-10\n",
                    "        self.eV = 1.6021772e-12\n",
                    "        self.sigmaSB = 5.67051e-5\n",
                    "        self.sigmaT = 6.6524e-25\n",
                    "        self.Rg = 8.3145e7\n",
                    "        self.a0 = 5.29177e-9\n",
                    "        self.arad = 7.5646e-15\n",
                    "        \n",
                    '        print( "Constants defined...")\n',
                    "        return None\n",
                    "    \n",
                    "    \n",
                    "c = Constants()\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "import requests\n",
                    "\n",
                    "%%timeit\n",
                    "for i in range(100):\n",
                    "    x = i * 2\n",
                    "\n",
                    "%load_ext autoreload\n",
                    "%autoreload 2\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {
                "language": "python",
                "name": "python3",
            }
        },
    }
    with open("notebook.ipynb", "w") as f:
        json.dump(notebook, f)
    deps = detect_dependencies_from_notebook("notebook.ipynb")
    assert "numpy" in deps
    assert "pandas" in deps
    assert "sklearn" in deps
    assert "matplotlib" in deps
    assert "requests" in deps


def test_detect_dependencies_from_r_notebook(tmp_dir):
    """Test detection of dependencies from an R Jupyter notebook."""
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "library(ggplot2)\n",
                    "library(dplyr)\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {
                "language": "r",
                "name": "ir",
            }
        },
    }
    with open("notebook.ipynb", "w") as f:
        json.dump(notebook, f)
    deps = detect_dependencies_from_notebook("notebook.ipynb")
    assert "ggplot2" in deps
    assert "dplyr" in deps


def test_create_python_requirements_file(tmp_dir):
    """Test creation of requirements.txt file."""
    deps = ["numpy", "pandas", "scikit-learn"]
    output_path = "requirements.txt"
    create_python_requirements_file(deps, output_path)
    assert os.path.exists(output_path)
    with open(output_path, "r") as f:
        content = f.read()
    assert "numpy" in content
    assert "pandas" in content
    assert "scikit-learn" in content


def test_create_julia_project_file(tmp_dir):
    """Test creation of Julia Project.toml file."""
    deps = ["DataFrames", "CSV", "Plots"]
    output_path = "Project.toml"
    create_julia_project_file(deps, output_path)
    assert os.path.exists(output_path)
    with open(output_path, "r") as f:
        content = f.read()
    assert "DataFrames" in content
    assert "CSV" in content
    assert "Plots" in content
    assert "[deps]" in content


def test_create_r_description_file(tmp_dir):
    """Test creation of R DESCRIPTION file."""
    deps = ["ggplot2", "dplyr", "tidyr"]
    output_path = "DESCRIPTION"

    create_r_description_file(deps, output_path)

    assert os.path.exists(output_path)

    with open(output_path, "r") as f:
        content = f.read()

    assert "ggplot2" in content
    assert "dplyr" in content
    assert "tidyr" in content
    assert "Imports:" in content
    # The Package field reflects the project name (sanitized to a valid R
    # package name), not a hard-coded placeholder
    from calkit.environments import create_r_description_content

    content = create_r_description_content(deps, project_name="AI-Games")
    assert "Package: AI.Games" in content
    assert "CalkitProject" not in content
    # Names that don't start with a letter get a valid prefix
    content = create_r_description_content(deps, project_name="2023-study")
    package_line = [
        ln for ln in content.splitlines() if ln.startswith("Package:")
    ][0]
    package_name = package_line.split(":", 1)[1].strip()
    assert package_name[0].isalpha()


def test_create_files_in_subdirectory(tmp_dir):
    """Test that spec files can be created in subdirectories."""
    deps = ["numpy"]
    output_path = ".calkit/envs/test-env/requirements.txt"

    create_python_requirements_file(deps, output_path)

    assert os.path.exists(output_path)
    assert os.path.exists(".calkit/envs/test-env")


def test_is_figure_path():
    """Figures must live in a figure-named directory."""
    from calkit.detect import is_figure_path

    # Detected: image-like extension under a figure directory, at any depth.
    assert is_figure_path("figures/result.png")
    assert is_figure_path("paper/figs/plot.pdf")
    assert is_figure_path("Plots/Fig1.SVG")
    # Plotly JSON under a figure-only directory counts as a figure.
    assert is_figure_path("figures/interactive.json")
    # Not detected: right extension, wrong (or no) directory.
    assert not is_figure_path("result.png")
    assert not is_figure_path("results/result.png")
    assert not is_figure_path("output/plot.pdf")
    assert not is_figure_path("img/logo.png")
    # JSON under a data directory is not a figure.
    assert not is_figure_path("data/records.json")
    # Non-figure extension under a figure directory.
    assert not is_figure_path("figures/notes.txt")


def test_is_dataset_path():
    """Datasets must live in a data-named directory."""
    from calkit.detect import is_dataset_path

    assert is_dataset_path("data/raw.csv")
    assert is_dataset_path("datasets/measurements.parquet")
    assert is_dataset_path("project/Data/records.json")
    # Wrong directory.
    assert not is_dataset_path("results/raw.csv")
    assert not is_dataset_path("raw.csv")
    # A .json under a figure-only dir is a figure, not a dataset.
    assert not is_dataset_path("figures/plot.json")
    # Non-dataset extension under a data directory.
    assert not is_dataset_path("data/readme.md")


def test_detect_figures():
    """detect_figures filters hidden and reserved paths."""
    from calkit.detect import detect_figures

    candidates = [
        "figures/a.png",
        "figs/b.pdf",
        "result.png",
        ".cache/figures/c.png",
        "figures/reserved.png",
    ]
    out = detect_figures(candidates, reserved_paths=["figures/reserved.png"])
    assert out == ["figs/b.pdf", "figures/a.png"]
    # Files inside a reserved directory are excluded too.
    out = detect_figures(
        ["figures/sub/x.png", "figures/y.png"], reserved_paths=["figures/sub"]
    )
    assert out == ["figures/y.png"]


def test_detect_datasets():
    """detect_datasets excludes figures and collapses folders."""
    from calkit.detect import detect_datasets

    candidates = [
        "data/a.csv",
        "data/sub/b.csv",
        "data/sub/c.csv",
        "figures/plot.json",
        ".venv/data/d.csv",
    ]
    out = detect_datasets(candidates, figure_paths=["figures/plot.json"])
    # data/sub holds two files, so it collapses to the folder; data/a.csv has
    # only one file in its folder, so it stays a file.
    assert out == ["data/a.csv", "data/sub"]


def test_is_result_path():
    """Results are data-like files under a results-named directory."""
    from calkit.detect import is_result_path

    assert is_result_path("results/metrics.json")
    assert is_result_path("results/summary.csv")
    assert is_result_path("project/result/table.html")
    # Wrong directory.
    assert not is_result_path("metrics.json")
    assert not is_result_path("data/raw.csv")
    # A figure under results is not a result.
    assert not is_result_path("results/plot.png")


def test_is_presentation_path():
    """Presentations are slide decks by directory or by name."""
    from calkit.detect import is_presentation_path

    assert is_presentation_path("slides/deck.pdf")
    assert is_presentation_path("presentations/kickoff.pptx")
    # Presentation-like name anywhere.
    assert is_presentation_path("slides.pdf")
    assert is_presentation_path("docs/presentation.pdf")
    # A PDF that isn't a slide deck and isn't in a presentation dir.
    assert not is_presentation_path("paper/manuscript.pdf")
    # A figure PDF is not a presentation.
    assert not is_presentation_path("figures/plot.pdf")


def test_is_publication_path():
    """Publications are documents by directory or by name."""
    from calkit.detect import is_publication_path

    assert is_publication_path("paper/manuscript.pdf")
    assert is_publication_path("publications/report.docx")
    assert is_publication_path("thesis/main.tex")
    # Publication-like name anywhere.
    assert is_publication_path("manuscript.pdf")
    assert is_publication_path("docs/main.tex")
    # A slide deck or figure is not a publication.
    assert not is_publication_path("slides/deck.pdf")
    assert not is_publication_path("figures/plot.pdf")
    # A document outside a publication dir without a publication name.
    assert not is_publication_path("notes/random.pdf")


def test_detect_artifact_kind():
    """Artifact kind is inferred from the path, with figures taking priority."""
    from calkit.detect import detect_artifact_kind

    assert detect_artifact_kind("figures/plot.png") == "figure"
    assert detect_artifact_kind("slides/slides.pdf") == "presentation"
    assert detect_artifact_kind("paper/manuscript.pdf") == "publication"
    assert detect_artifact_kind("data/raw.csv") == "dataset"
    # A figure PDF wins over presentation/publication detection.
    assert detect_artifact_kind("figures/diagram.pdf") == "figure"
    # Nothing recognizable.
    assert detect_artifact_kind("notes.txt") is None


def test_detect_results_and_presentations():
    """detect_results/detect_presentations filter hidden and reserved paths."""
    from calkit.detect import detect_presentations, detect_results

    results = detect_results(
        [
            "results/a.json",
            "results/b.csv",
            "data/c.csv",
            ".cache/results/d.json",
        ],
        reserved_paths=["results/b.csv"],
    )
    assert results == ["results/a.json"]
    presentations = detect_presentations(
        ["slides/x.pdf", "presentation.pdf", "figures/p.pdf"]
    )
    assert presentations == ["presentation.pdf", "slides/x.pdf"]


def test_detect_project_artifacts_includes_results_and_presentations(tmp_dir):
    """detect_project_artifacts reports the new kinds for a real repo."""
    import subprocess

    import calkit.detect

    subprocess.check_call(["git", "init", "-q"])
    os.makedirs("results")
    os.makedirs("slides")
    with open("results/metrics.json", "w") as f:
        f.write("{}")
    with open("slides/deck.pdf", "w") as f:
        f.write("%PDF-1.4")
    out = calkit.detect.detect_project_artifacts(ck_info={})
    assert "results/metrics.json" in out["results"]
    assert "slides/deck.pdf" in out["presentations"]
