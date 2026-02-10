"""Functionality for detecting inputs and outputs from scripts, notebooks, and commands."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from typing import Literal


def detect_python_script_io(script_path: str) -> dict[str, list[str]]:
    """Detect inputs and outputs from a Python script using static analysis."""
    inputs = []
    outputs = []
    if not os.path.exists(script_path):
        return {"inputs": inputs, "outputs": outputs}
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, filename=script_path)
    except (SyntaxError, UnicodeDecodeError):
        return {"inputs": inputs, "outputs": outputs}
    script_dir = os.path.dirname(script_path) if script_path else "."
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_file = _resolve_python_import(alias.name, script_dir)
                if local_file:
                    inputs.append(local_file)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                local_file = _resolve_python_import(node.module, script_dir)
                if local_file:
                    inputs.append(local_file)
            elif node.level > 0:
                parent_dir = script_dir
                for _ in range(node.level - 1):
                    parent_dir = os.path.dirname(parent_dir)
                if node.module:
                    module_path = node.module.replace(".", os.sep)
                    local_file = _resolve_python_import(
                        module_path, parent_dir
                    )
                    if local_file:
                        inputs.append(local_file)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name == "open" and len(node.args) >= 1:
                    path = _extract_string_from_node(node.args[0])
                    if path:
                        mode = "r"
                        if len(node.args) >= 2:
                            mode_str = _extract_string_from_node(node.args[1])
                            if mode_str:
                                mode = mode_str
                        for keyword in node.keywords:
                            if keyword.arg == "mode":
                                mode_str = _extract_string_from_node(
                                    keyword.value
                                )
                                if mode_str:
                                    mode = mode_str
                        if "w" in mode or "a" in mode or "x" in mode:
                            outputs.append(path)
                        else:
                            inputs.append(path)
            elif isinstance(node.func, ast.Attribute):
                module = getattr(node.func.value, "id", None)
                if module and isinstance(module, str):
                    func = node.func.attr
                    if module == "pd" and func.startswith("read_"):
                        if len(node.args) >= 1:
                            path = _extract_string_from_node(node.args[0])
                            if path:
                                inputs.append(path)
                    elif module in [
                        "df",
                        "data",
                        "frame",
                        "result",
                    ] and func.startswith("to_"):
                        if len(node.args) >= 1:
                            path = _extract_string_from_node(node.args[0])
                            if path:
                                outputs.append(path)
                    elif module == "np" and func in [
                        "load",
                        "loadtxt",
                        "genfromtxt",
                        "fromfile",
                    ]:
                        if len(node.args) >= 1:
                            path = _extract_string_from_node(node.args[0])
                            if path:
                                inputs.append(path)
                    elif module == "np" and func in [
                        "save",
                        "savetxt",
                        "savez",
                        "savez_compressed",
                    ]:
                        if len(node.args) >= 1:
                            path = _extract_string_from_node(node.args[0])
                            if path:
                                outputs.append(path)
                    elif func == "savefig":
                        if len(node.args) >= 1:
                            path = _extract_string_from_node(node.args[0])
                            if path:
                                outputs.append(path)
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    return {"inputs": inputs, "outputs": outputs}


def detect_julia_script_io(script_path: str) -> dict[str, list[str]]:
    """Detect inputs and outputs from a Julia script using regex patterns."""
    inputs = []
    outputs = []
    if not os.path.exists(script_path):
        return {"inputs": inputs, "outputs": outputs}
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return {"inputs": inputs, "outputs": outputs}
    script_dir = os.path.dirname(script_path) if script_path else "."
    content = re.sub(r"#.*$", "", content, flags=re.MULTILINE)
    include_pattern = r'include\s*\(\s*["\']([^"\']+\.jl)["\']\s*\)'
    include_matches = re.findall(include_pattern, content)
    for match in include_matches:
        if not os.path.isabs(match):
            full_path = os.path.join(script_dir, match)
            if os.path.exists(full_path):
                inputs.append(os.path.relpath(full_path))
            elif _is_valid_project_path(match):
                inputs.append(match)
    read_patterns = [
        r'open\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']r["\']',
        r'open\s*\(\s*["\']([^"\']+)["\']\s*\)',
        r'CSV\.(?:read|File)\s*\(\s*["\']([^"\']+)["\']',
        r'readdlm\s*\(\s*["\']([^"\']+)["\']',
        r'load\s*\(\s*["\']([^"\']+)["\']',
        r'JLD2?\.load\s*\(\s*["\']([^"\']+)["\']',
    ]
    write_patterns = [
        r'open\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']w["\']',
        r'open\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']a["\']',
        r'CSV\.write\s*\(\s*["\']([^"\']+)["\']',
        r'writedlm\s*\(\s*["\']([^"\']+)["\']',
        r'save\s*\(\s*["\']([^"\']+)["\']',
        r'JLD2?\.save\s*\(\s*["\']([^"\']+)["\']',
        r'savefig\s*\(\s*["\']([^"\']+)["\']',
    ]
    for pattern in read_patterns:
        matches = re.findall(pattern, content)
        inputs.extend(matches)
    for pattern in write_patterns:
        matches = re.findall(pattern, content)
        outputs.extend(matches)
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    return {"inputs": inputs, "outputs": outputs}


def detect_shell_script_io(script_path: str) -> dict[str, list[str]]:
    """Detect inputs and outputs from a shell script using regex patterns."""
    inputs = []
    outputs = []
    if not os.path.exists(script_path):
        return {"inputs": inputs, "outputs": outputs}
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return {"inputs": inputs, "outputs": outputs}
    content = re.sub(r"#.*$", "", content, flags=re.MULTILINE)
    # Output patterns
    output_patterns = [
        r">\s*(\S+)",
        r">>\s*(\S+)",
        r"\bcp\s+\S+\s+(\S+)",
        r"\bmv\s+\S+\s+(\S+)",
    ]
    for pattern in output_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            match = match.strip("\"'")
            outputs.append(match)
    # For input patterns, look for files with extensions after commands
    input_patterns = [
        r"<\s+(\S+)",
        r"\bcat\s+([\S\.]+)",
        r"\bhead\s+.*?([\S\.]+\.[\w]+)",
        r"\btail\s+.*?([\S\.]+\.[\w]+)",
        r"\bgrep\s+[^\s]+\s+([\S\.]+)",
        r"\bawk\s+[^\s]+\s+([\S\.]+)",
        r"\bsed\s+[^\s]+\s+([\S\.]+)",
        r"\bcut\s+[^\s]+\s+([\S\.]+)",
        r"\bsort\s+([\S\.]+)",
    ]
    for pattern in input_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            # Handle multiple files
            for file in match.split():
                file = file.strip("\"'").strip()
                if (
                    file
                    and not file.startswith("-")
                    and not file.startswith("/dev/")
                ):
                    inputs.append(file)
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    return {"inputs": inputs, "outputs": outputs}


def detect_jupyter_notebook_io(
    notebook_path: str,
    language: Literal["python", "julia", "r"] | None = None,
) -> dict[str, list[str]]:
    """Detect inputs and outputs from a Jupyter notebook."""
    inputs = []
    outputs = []
    if not os.path.exists(notebook_path):
        return {"inputs": inputs, "outputs": outputs}
    try:
        with open(notebook_path, "r", encoding="utf-8") as f:
            nb = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"inputs": inputs, "outputs": outputs}
    if language is None:
        metadata = nb.get("metadata", {})
        kernel_info = metadata.get("kernelspec", {})
        kernel_lang = kernel_info.get("language", "").lower()
        if "python" in kernel_lang:
            language = "python"
        elif "julia" in kernel_lang:
            language = "julia"
        elif kernel_lang == "r":
            language = "r"
        else:
            language = "python"
    code_cells = [
        cell for cell in nb.get("cells", []) if cell.get("cell_type") == "code"
    ]
    for cell in code_cells:
        source = cell.get("source", [])
        if isinstance(source, list):
            code = "".join(source)
        else:
            code = source
        notebook_dir = os.path.dirname(notebook_path) if notebook_path else "."
        if language == "python":
            cell_io = _detect_python_code_io(code, script_dir=notebook_dir)
        elif language == "julia":
            cell_io = _detect_julia_code_io(code, script_dir=notebook_dir)
        elif language == "r":
            cell_io = _detect_r_code_io(code)
        else:
            cell_io = {"inputs": [], "outputs": []}
        inputs.extend(cell_io["inputs"])
        outputs.extend(cell_io["outputs"])
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    return {"inputs": inputs, "outputs": outputs}


def detect_latex_io(
    tex_path: str, environment: str | None = None
) -> dict[str, list[str]]:
    """Detect inputs and outputs from a LaTeX file using latexmk -deps."""
    inputs = []
    outputs = []
    if not os.path.exists(tex_path):
        return {"inputs": inputs, "outputs": outputs}
    # Try to detect dependencies using latexmk -deps
    try:
        # Build the command to run latexmk -deps
        cmd = []
        if environment and environment != "_system":
            # Run in the specified environment
            cmd = ["calkit", "xenv", "-n", environment, "--no-check", "--"]
        cmd.extend(["latexmk", "-deps", tex_path])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            # Parse the latexmk -deps output
            # Format is typically: target: dep1 dep2 dep3
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Parse Makefile-style dependency lines
                if ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        deps = parts[1].strip().split()
                        for dep in deps:
                            # Clean up the dependency path
                            dep = dep.strip()
                            if dep and _is_valid_project_path(dep):
                                # Filter out the main tex file itself
                                if dep != tex_path:
                                    inputs.append(dep)
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        # If latexmk fails, fall back to regex-based detection
        try:
            with open(tex_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            return {"inputs": inputs, "outputs": outputs}
        # Remove comments
        content = re.sub(r"(?<!\\)%.*$", "", content, flags=re.MULTILINE)
        # Define patterns with their handling types
        patterns = [
            (r"\\input\{([^}]+)\}", "tex"),
            (r"\\include\{([^}]+)\}", "tex"),
            (r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", "file"),
            (r"\\bibliography\{([^}]+)\}", "bib"),
            (r"\\addbibresource\{([^}]+)\}", "bib"),
        ]
        for pattern, pattern_type in patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                if pattern_type == "bib":
                    files = [f.strip() for f in match.split(",")]
                    for f in files:
                        if not f.endswith(".bib"):
                            f += ".bib"
                        inputs.append(f)
                elif pattern_type == "tex":
                    if not match.endswith(".tex"):
                        inputs.append(match + ".tex")
                    else:
                        inputs.append(match)
                else:
                    inputs.append(match)
    # Filter and deduplicate inputs
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    inputs = list(dict.fromkeys(inputs))
    return {"inputs": inputs, "outputs": outputs}


def detect_shell_command_io(command: str) -> dict[str, list[str]]:
    """Detect inputs and outputs from a shell command string."""
    inputs = []
    outputs = []
    input_redirects = re.findall(r"<\s*(\S+)", command)
    inputs.extend([f.strip("\"'") for f in input_redirects])
    output_redirects = re.findall(r">>?\s*(\S+)", command)
    outputs.extend([f.strip("\"'") for f in output_redirects])
    words = command.split()
    for i, word in enumerate(words):
        if word.startswith("-"):
            continue
        if "/" in word or "." in word:
            clean = word.strip("\"'")
            if _is_valid_project_path(clean):
                if i > 0 and words[0] in [
                    "cat",
                    "head",
                    "tail",
                    "grep",
                    "awk",
                    "sed",
                ]:
                    inputs.append(clean)
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    return {"inputs": inputs, "outputs": outputs}


def _extract_string_from_node(node: ast.AST) -> str | None:
    """Extract a string value from an AST node if it's a constant string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Str) and isinstance(node.s, str):
        return node.s
    return None


def _is_valid_project_path(path: str) -> bool:
    """Check if a path is valid for a project dependency/output."""
    if not path:
        return False
    if path.startswith(("http://", "https://", "ftp://", "s3://", "gs://")):
        return False
    if os.path.isabs(path):
        return False
    if ".." in path:
        return False
    if path.startswith(("/dev/", "/proc/", "/sys/", "~")):
        return False
    return True


def _detect_python_code_io(
    code: str, script_dir: str = "."
) -> dict[str, list[str]]:
    """Detect I/O from Python code string (used for notebook cells)."""
    inputs = []
    outputs = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"inputs": inputs, "outputs": outputs}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_file = _resolve_python_import(alias.name, script_dir)
                if local_file:
                    inputs.append(local_file)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                local_file = _resolve_python_import(node.module, script_dir)
                if local_file:
                    inputs.append(local_file)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name == "open" and len(node.args) >= 1:
                    path = _extract_string_from_node(node.args[0])
                    if path:
                        mode = "r"
                        if len(node.args) >= 2:
                            mode_str = _extract_string_from_node(node.args[1])
                            if mode_str:
                                mode = mode_str
                        for keyword in node.keywords:
                            if keyword.arg == "mode":
                                mode_str = _extract_string_from_node(
                                    keyword.value
                                )
                                if mode_str:
                                    mode = mode_str
                        if "w" in mode or "a" in mode or "x" in mode:
                            outputs.append(path)
                        else:
                            inputs.append(path)
            elif isinstance(node.func, ast.Attribute):
                module = getattr(node.func.value, "id", None)
                if module and isinstance(module, str):
                    func = node.func.attr
                    if module == "pd" and func.startswith("read_"):
                        if len(node.args) >= 1:
                            path = _extract_string_from_node(node.args[0])
                            if path:
                                inputs.append(path)
                    elif func.startswith("to_"):
                        if len(node.args) >= 1:
                            path = _extract_string_from_node(node.args[0])
                            if path:
                                outputs.append(path)
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    return {"inputs": inputs, "outputs": outputs}


def _detect_julia_code_io(
    code: str, script_dir: str = "."
) -> dict[str, list[str]]:
    """Detect I/O from Julia code string (used for notebook cells)."""
    inputs = []
    outputs = []
    code = re.sub(r"#.*$", "", code, flags=re.MULTILINE)
    include_pattern = r'include\s*\(\s*["\']([^"\']+\.jl)["\']\s*\)'
    include_matches = re.findall(include_pattern, code)
    for match in include_matches:
        if not os.path.isabs(match):
            full_path = os.path.join(script_dir, match)
            if os.path.exists(full_path):
                inputs.append(os.path.relpath(full_path))
            elif _is_valid_project_path(match):
                inputs.append(match)
    read_patterns = [
        r'open\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']r["\']',
        r'open\s*\(\s*["\']([^"\']+)["\']\s*\)',
        r'CSV\.(?:read|File)\s*\(\s*["\']([^"\']+)["\']',
        r'readdlm\s*\(\s*["\']([^"\']+)["\']',
    ]
    write_patterns = [
        r'open\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']w["\']',
        r'CSV\.write\s*\(\s*["\']([^"\']+)["\']',
        r'writedlm\s*\(\s*["\']([^"\']+)["\']',
    ]
    for pattern in read_patterns:
        inputs.extend(re.findall(pattern, code))
    for pattern in write_patterns:
        outputs.extend(re.findall(pattern, code))
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    return {"inputs": inputs, "outputs": outputs}


def _resolve_python_import(
    module_name: str, search_dir: str = "."
) -> str | None:
    """Resolve a Python import to a local file path if it exists."""
    module_path = module_name.replace(".", os.sep)
    file_path = os.path.join(search_dir, module_path + ".py")
    if os.path.exists(file_path) and _is_valid_project_path(
        os.path.relpath(file_path)
    ):
        return os.path.relpath(file_path)
    init_path = os.path.join(search_dir, module_path, "__init__.py")
    if os.path.exists(init_path) and _is_valid_project_path(
        os.path.relpath(init_path)
    ):
        return os.path.relpath(init_path)
    return None


def _detect_r_code_io(code: str) -> dict[str, list[str]]:
    """Detect I/O from R code string (used for notebook cells)."""
    inputs = []
    outputs = []
    code = re.sub(r"#.*$", "", code, flags=re.MULTILINE)
    read_patterns = [
        r'read\.(?:csv|table|delim|tsv)\s*\(\s*["\']([^"\']+)["\']',
        r'readRDS\s*\(\s*["\']([^"\']+)["\']',
        r'load\s*\(\s*["\']([^"\']+)["\']',
        r'read_csv\s*\(\s*["\']([^"\']+)["\']',
    ]
    write_patterns = [
        r'write\.(?:csv|table)\s*\(\s*[^,]+,\s*["\']([^"\']+)["\']',
        r'saveRDS\s*\(\s*[^,]+,\s*["\']([^"\']+)["\']',
        r'save\s*\([^,]+,\s*file\s*=\s*["\']([^"\']+)["\']',
        r'ggsave\s*\(\s*["\']([^"\']+)["\']',
    ]
    for pattern in read_patterns:
        inputs.extend(re.findall(pattern, code))
    for pattern in write_patterns:
        outputs.extend(re.findall(pattern, code))
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    return {"inputs": inputs, "outputs": outputs}


def generate_stage_name(
    stage_kind: str, first_arg: str, cmd: list[str]
) -> str | None:
    """Generate a stage name from the stage kind and command.

    Parameters
    ----------
    stage_kind : str
        The kind of stage (e.g., "python-script", "shell-command").
    first_arg : str
        The first argument of the command.
    cmd : list[str]
        The full command as a list of strings.

    Returns
    -------
    str | None
        The generated stage name, or None if it cannot be determined.
    """
    # Only auto-generate names for script/notebook stages
    if stage_kind not in [
        "jupyter-notebook",
        "python-script",
        "julia-script",
        "matlab-script",
        "shell-script",
        "latex",
    ]:
        return None
    # Extract base name from the script/notebook path
    base_name = os.path.splitext(os.path.basename(first_arg))[0]
    stage_name = base_name
    # Append args if present (skip first arg which is the script itself)
    if len(cmd) > 1:
        args_part = "-".join(cmd[1:])
        stage_name += "-" + args_part
    # Convert to kebab-case
    stage_name = stage_name.replace("_", "-").lower()
    return stage_name
