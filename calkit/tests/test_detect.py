"""Tests for the ``calkit.detect`` module."""

import json
import os

from calkit.detect import (
    detect_io,
    detect_julia_script_io,
    detect_jupyter_notebook_io,
    detect_latex_io,
    detect_python_script_io,
    detect_r_script_io,
    detect_shell_command_io,
    detect_shell_script_io,
    generate_stage_name,
)


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
    """Test detection of inputs and outputs from Python Jupyter notebooks."""
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import pandas as pd\n",
                    "from helper import process\n",
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
    # Create the helper module
    with open("helper.py", "w") as f:
        f.write("def process(): pass")
    result = detect_jupyter_notebook_io("notebook.ipynb")
    # Check detected inputs
    assert "data.csv" in result["inputs"]
    assert "input.txt" in result["inputs"]
    assert "helper.py" in result["inputs"]
    # Check detected outputs
    assert "output.csv" in result["outputs"]
    assert "result.txt" in result["outputs"]


def test_detect_jupyter_notebook_io_matplotlib(tmp_dir):
    """Test detection of matplotlib savefig in Python Jupyter notebooks."""
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import matplotlib.pyplot as plt\n",
                    "import numpy as np\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "x = np.linspace(0, 10, 100)\n",
                    "y = np.sin(x)\n",
                    "plt.plot(x, y)\n",
                    "plt.savefig('plot.png')\n",
                ],
            },
            {
                "cell_type": "code",
                "source": [
                    "fig, ax = plt.subplots()\n",
                    "ax.plot(x, y)\n",
                    "fig.savefig('result.pdf')\n",
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
    result = detect_jupyter_notebook_io("notebook.ipynb")
    # Check detected outputs
    assert "plot.png" in result["outputs"]
    assert "result.pdf" in result["outputs"]


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
    import os

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
    # Test Python script with args
    name = generate_stage_name(["process.py", "--verbose", "input.txt"])
    assert name == "process-verbose-input-txt"
    # Test Julia script
    name = generate_stage_name(["analyze.jl"])
    assert name == "analyze"
    # Test MATLAB script
    name = generate_stage_name(["run_simulation.m"])
    assert name == "run-simulation"
    # Test notebook
    name = generate_stage_name(["analysis.ipynb"])
    assert name == "analysis"
    # Test shell script
    name = generate_stage_name(["build.sh", "production"])
    assert name == "build-production"
    # Test LaTeX document
    name = generate_stage_name(["paper.tex"])
    assert name == "paper"
    # Test with path (should use basename)
    name = generate_stage_name(["scripts/process_data.py"])
    assert name == "process-data"
    # Test underscore to dash conversion
    name = generate_stage_name(["my_script.py"])
    assert name == "my-script"
    # Test shell command (returns command name)
    name = generate_stage_name(["echo", "Hello", "World"])
    assert name == "echo-hello-world"
    # Test matlab command with parentheses (should be removed) and -batch (should be removed)
    name = generate_stage_name(["matlab", "-batch", "disp('test')"])
    assert name == "matlab-disptest"
    # Test matlab command with -batch and other flags
    name = generate_stage_name(["matlab", "-batch", "run_script"])
    assert name == "matlab-run-script"
    # Test empty command
    name = generate_stage_name([])
    assert name == "stage"
    # Test with options that have multiple dashes (should consolidate)
    name = generate_stage_name(["script.py", "--flag1", "--flag2"])
    assert name == "script-flag1-flag2"
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
