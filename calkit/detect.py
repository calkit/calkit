"""Functionality for detecting inputs, outputs, and dependencies from scripts,
notebooks, and commands.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Literal

NotebookLanguage = Literal["python", "julia", "r"]


def detect_python_script_io(
    script_path: str,
    wdir: str | None = None,
) -> dict[str, list[str]]:
    """Detect inputs and outputs from a Python script using static analysis."""
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
    effective_wdir = wdir or "."
    return _detect_python_code_io(
        content,
        script_dir=script_dir,
        working_dir=effective_wdir,
        current_dir=effective_wdir,
    )


def detect_r_script_io(
    script_path: str,
    wdir: str | None = None,
) -> dict[str, list[str]]:
    """Detect inputs and outputs from an R script using regex patterns.

    Parameters
    ----------
    script_path : str
        Path to the R script file.
    wdir : str | None
        Working directory from which the script will be executed.
        Defaults to current directory.

    Returns
    -------
    dict[str, list[str]]
        Dictionary with 'inputs' and 'outputs' keys.
    """
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
    effective_wdir = wdir or "."
    return _detect_r_code_io(
        content,
        script_dir=script_dir,
        wdir=effective_wdir,
        project_root=effective_wdir,
    )


def detect_julia_script_io(
    script_path: str,
    wdir: str | None = None,
) -> dict[str, list[str]]:
    """Detect inputs and outputs from a Julia script using regex patterns.

    Parameters
    ----------
    script_path : str
        Path to the Julia script file.
    wdir : str | None
        Working directory from which the script will be executed.
        Defaults to current directory.

    Returns
    -------
    dict[str, list[str]]
        Dictionary with 'inputs' and 'outputs' keys.
    """
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
    effective_wdir = wdir or "."
    content = re.sub(r"#.*$", "", content, flags=re.MULTILINE)
    julia_vars = _extract_julia_string_assignments(content)
    include_pattern = r'include\s*\(\s*["\']([^"\']+\.jl)["\']\s*\)'
    include_matches = re.findall(include_pattern, content)
    for match in include_matches:
        if not os.path.isabs(match):
            full_path = os.path.join(script_dir, match)
            if os.path.exists(full_path):
                inputs.append(Path(os.path.relpath(full_path)).as_posix())
            elif _is_valid_project_path(match):
                inputs.append(match)
    read_patterns = [
        r'open\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))\s*,\s*["\']r["\']',
        r'open\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))\s*\)',
        r'CSV\.(?:read|File)\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
        r'readdlm\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
        r'load\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
        r'JLD2?\.load\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
    ]
    write_patterns = [
        r'open\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))\s*,\s*["\']w["\']',
        r'open\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))\s*,\s*["\']a["\']',
        r'CSV\.write\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
        r'writedlm\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
        r'save\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
        r'JLD2?\.save\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
        r'savefig\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
    ]
    for pattern in read_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            resolved = _resolve_julia_path_expr(match, julia_vars)
            if resolved:
                inputs.append(resolved)
    for pattern in write_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            resolved = _resolve_julia_path_expr(match, julia_vars)
            if resolved:
                outputs.append(resolved)
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    # Resolve paths relative to working directory
    inputs = _resolve_paths_to_wdir(inputs, script_dir, effective_wdir)
    outputs = _resolve_paths_to_wdir(outputs, script_dir, effective_wdir)
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    return {"inputs": inputs, "outputs": outputs}


def detect_shell_script_io(
    script_path: str,
    wdir: str | None = None,
) -> dict[str, list[str]]:
    """Detect inputs and outputs from a shell script using regex patterns.

    Parameters
    ----------
    script_path : str
        Path to the shell script file.
    wdir : str | None
        Working directory from which the script will be executed.
        Defaults to current directory.

    Returns
    -------
    dict[str, list[str]]
        Dictionary with 'inputs' and 'outputs' keys.
    """
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
    effective_wdir = wdir or "."
    content = re.sub(r"#.*$", "", content, flags=re.MULTILINE)
    # Output patterns (>> must come before > to avoid matching
    # the first > in >>)
    output_patterns = [
        r">>\s*(\S+)",  # append redirection
        r"(?<!>)>\s*(\S+)",  # single redirection, not part of '>>'
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
    # Resolve paths relative to working directory
    inputs = _resolve_paths_to_wdir(inputs, script_dir, effective_wdir)
    outputs = _resolve_paths_to_wdir(outputs, script_dir, effective_wdir)
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    return {"inputs": inputs, "outputs": outputs}


def _resolve_paths_to_wdir(
    paths: list[str], script_dir: str, wdir: str
) -> list[str]:
    """Resolve paths from script directory to working directory.

    When a script is in a subdirectory (e.g., scripts/process.R),
    its relative paths should be resolved from the working directory
    where the command is executed, not from the script's directory.

    Parameters
    ----------
    paths : list[str]
        List of file paths detected in the script.
    script_dir : str
        Directory containing the script.
    wdir : str
        Working directory from which the script will be executed.

    Returns
    -------
    list[str]
        Paths resolved relative to wdir.
    """
    if script_dir == wdir or script_dir == ".":
        return paths
    resolved = []
    for path in paths:
        if os.path.isabs(path):
            # Absolute paths stay as-is (though they should be filtered already)
            resolved.append(path)
        else:
            # Path is relative - assume it's relative to wdir, not script_dir
            # Just pass it through as-is
            resolved.append(path)
    return resolved


def _extract_directory_changes(code: str, current_dir: str = ".") -> str:
    """Extract final working directory after all %cd and os.chdir() calls in
    code.

    Parameters
    ----------
    code : str
        Python code potentially containing %cd magic or os.chdir() calls.
    current_dir : str
        Starting directory for resolution.

    Returns
    -------
    str
        Final working directory after all changes.
    """
    working_dir = current_dir
    # Handle Jupyter %cd magic commands
    for line in code.split("\n"):
        stripped = line.strip()
        if stripped.startswith("%cd "):
            chdir_path = stripped[4:].strip()
            chdir_path = chdir_path.strip("'\"")
            if chdir_path:
                working_dir = os.path.normpath(
                    os.path.join(working_dir, chdir_path)
                )
    # Handle os.chdir() calls
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "os"
                        and node.func.attr == "chdir"
                        and len(node.args) >= 1
                    ):
                        chdir_path = _extract_string_from_node(node.args[0])
                        if chdir_path:
                            working_dir = os.path.normpath(
                                os.path.join(working_dir, chdir_path)
                            )
    except SyntaxError:
        pass
    return working_dir


def language_from_notebook(
    notebook_path: str, notebook: dict | None = None
) -> NotebookLanguage | None:
    """Detect notebook language from kernelspec metadata."""
    if notebook is None:
        if not os.path.exists(notebook_path):
            return
        try:
            with open(notebook_path, "r", encoding="utf-8") as f:
                notebook = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
    assert notebook is not None
    metadata = notebook.get("metadata", {})
    kernel_info = metadata.get("kernelspec", {})
    kernel_lang = kernel_info.get("language", "").lower()
    if "python" in kernel_lang:
        return "python"
    if "julia" in kernel_lang:
        return "julia"
    if kernel_lang == "r":
        return "r"
    return


def detect_jupyter_notebook_io(
    notebook_path: str,
    language: NotebookLanguage | None = None,
    wdir: str | None = None,
) -> dict[str, list[str]]:
    """Detect inputs and outputs from a Jupyter notebook.

    Extracts all code cells and passes them to the appropriate
    language-specific detection function. Detection functions handle
    variable tracking and directory changes across cells.
    """
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
        detected = language_from_notebook(notebook_path, notebook=nb)
        language = detected if detected is not None else "python"
    code_cells = [
        cell for cell in nb.get("cells", []) if cell.get("cell_type") == "code"
    ]
    # Concatenate all code cells with newlines to preserve structure
    full_code = "\n".join(
        "".join(cell.get("source", []))
        if isinstance(cell.get("source", []), list)
        else cell.get("source", "")
        for cell in code_cells
    )
    notebook_dir = os.path.dirname(notebook_path) if notebook_path else "."
    effective_wdir = wdir or "."
    if language == "python":
        return _detect_python_code_io(
            full_code,
            script_dir=notebook_dir,
            working_dir=effective_wdir,
            current_dir=notebook_dir,
        )
    elif language == "julia":
        return _detect_julia_code_io(full_code, script_dir=notebook_dir)
    elif language == "r":
        return _detect_r_code_io(full_code, script_dir=notebook_dir)
    else:
        return {"inputs": [], "outputs": []}


def detect_latex_io(tex_path: str) -> dict[str, list[str]]:
    """Detect inputs and outputs from a LaTeX file using static analysis."""
    inputs = []
    outputs = []
    if not os.path.exists(tex_path):
        return {"inputs": inputs, "outputs": outputs}
    # Get the directory of the LaTeX file for resolving relative references
    tex_dir = os.path.dirname(tex_path)
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

            def _resolve(name: str) -> str:
                return Path(
                    os.path.normpath(os.path.join(tex_dir, name))
                ).as_posix()

            if pattern_type == "bib":
                files = [f.strip() for f in match.split(",")]
                for f in files:
                    if not f.endswith(".bib"):
                        f += ".bib"
                    # Resolve relative to the document directory
                    inputs.append(_resolve(f))
            elif pattern_type == "tex":
                filename = match
                if not filename.endswith(".tex"):
                    filename += ".tex"
                # Resolve relative to the document directory
                inputs.append(_resolve(filename))
            else:
                # Include graphics or other files
                # Resolve relative to the document directory
                inputs.append(_resolve(match))
    # Filter and deduplicate inputs
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    inputs = list(dict.fromkeys(inputs))
    return {"inputs": inputs, "outputs": outputs}


def detect_shell_command_io(command: str) -> dict[str, list[str]]:
    """Detect inputs and outputs from a shell command string."""
    from calkit.docker import extract_docker_run_inner_command

    inputs = []
    outputs = []
    analyzed_command = command
    inner_command = extract_docker_run_inner_command(command)
    if inner_command is not None:
        analyzed_command = " ".join(
            shlex.quote(part) for part in inner_command
        )
    input_redirects = re.findall(r"<\s*(\S+)", analyzed_command)
    inputs.extend([f.strip("\"'") for f in input_redirects])
    output_redirects = re.findall(r">>?\s*(\S+)", analyzed_command)
    outputs.extend([f.strip("\"'") for f in output_redirects])
    try:
        words = shlex.split(analyzed_command)
    except ValueError:
        words = analyzed_command.split()
    if words and words[0] in ["cp", "mv"]:
        operands = []
        for word in words[1:]:
            if word == "--":
                continue
            if word.startswith("-"):
                continue
            operands.append(word.strip("\"'"))
        if len(operands) >= 2:
            inputs.extend(operands[:-1])
            outputs.append(operands[-1])
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
    return None


def _is_os_path_join(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute):
        if node.func.attr == "join":
            value = node.func.value
            if isinstance(value, ast.Attribute):
                return (
                    value.attr == "path"
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "os"
                )
    return False


def _resolve_join_call(
    node: ast.Call, variables: dict[str, str]
) -> str | None:
    parts: list[str] = []
    for arg in node.args:
        part = _resolve_path_expr(arg, variables)
        if part is None:
            return None
        parts.append(part)
    if not parts:
        return "."
    return os.path.join(*parts)


def _resolve_path_expr(node: ast.AST, variables: dict[str, str]) -> str | None:
    # Direct string literal
    path = _extract_string_from_node(node)
    if path:
        return path
    # Variable reference
    if isinstance(node, ast.Name) and node.id in variables:
        return variables[node.id]
    # Path composition with / or +
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, (ast.Div, ast.Add)):
            left = _resolve_path_expr(node.left, variables)
            right = _resolve_path_expr(node.right, variables)
            if left and right:
                return os.path.join(left, right)
    # Path attribute access
    if isinstance(node, ast.Attribute):
        if node.attr == "parent":
            base = _resolve_path_expr(node.value, variables)
            if base:
                if base in [".", ""]:
                    return ".."
                return os.path.dirname(base)
    # Call expressions
    if isinstance(node, ast.Call):
        if _is_os_path_join(node):
            return _resolve_join_call(node, variables)
        if isinstance(node.func, ast.Name) and node.func.id == "join":
            return _resolve_join_call(node, variables)
        if isinstance(node.func, ast.Name) and node.func.id == "Path":
            if not node.args:
                return "."
            return _resolve_join_call(node, variables)
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "joinpath":
                base = _resolve_path_expr(node.func.value, variables)
                if base:
                    parts = [base]
                    for arg in node.args:
                        part = _resolve_path_expr(arg, variables)
                        if part is None:
                            return None
                        parts.append(part)
                    return os.path.join(*parts)
            if node.func.attr in ["absolute", "resolve"]:
                base = _resolve_path_expr(node.func.value, variables)
                if base:
                    return os.path.abspath(base)
            if node.func.attr == "cwd":
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "Path"
                ):
                    return "."
    return None


def _extract_variable_assignments(tree: ast.Module) -> dict[str, str]:
    """Extract simple string variable assignments from AST.

    Returns a dict mapping variable names to their string values.
    Only tracks direct assignments like: var = "path/to/file"
    """
    variables = {}

    def visit_statements(statements: list[ast.stmt]) -> None:
        for stmt in statements:
            if isinstance(stmt, ast.Assign):
                # Only handle simple single target assignments
                if len(stmt.targets) == 1:
                    target = stmt.targets[0]
                    if isinstance(target, ast.Name):
                        value = _resolve_path_expr(stmt.value, variables)
                        if value:
                            variables[target.id] = value
            elif isinstance(stmt, ast.AnnAssign):
                if (
                    isinstance(stmt.target, ast.Name)
                    and stmt.value is not None
                ):
                    value = _resolve_path_expr(stmt.value, variables)
                    if value:
                        variables[stmt.target.id] = value
            if isinstance(stmt, ast.If):
                visit_statements(stmt.body)
                visit_statements(stmt.orelse)
            elif isinstance(stmt, (ast.For, ast.While)):
                visit_statements(stmt.body)
                visit_statements(stmt.orelse)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                visit_statements(stmt.body)
            elif isinstance(stmt, ast.Try):
                visit_statements(stmt.body)
                visit_statements(stmt.orelse)
                visit_statements(stmt.finalbody)
                for handler in stmt.handlers:
                    visit_statements(handler.body)

    if isinstance(tree, ast.Module):
        visit_statements(tree.body)
    return variables


def _resolve_variable_in_call(
    node: ast.expr, variables: dict[str, str]
) -> str | None:
    """Try to resolve a file path from a call node that may reference a
    variable.

    Handles patterns like:
    - open(variable)
    - open("literal_path")
    - path_template.format(...)
    """
    # Direct path expression
    path = _resolve_path_expr(node, variables)
    if path:
        return path
    # For format calls: path_template.format(key=value) -> substitute template
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "format":
                # Get the string being formatted
                base_path = _resolve_variable_in_call(
                    node.func.value, variables
                )
                if base_path:
                    # Extract keyword arguments and substitute them
                    format_kwargs = {}
                    for keyword in node.keywords:
                        if keyword.arg:
                            value = _resolve_path_expr(
                                keyword.value, variables
                            )
                            if value:
                                format_kwargs[keyword.arg] = value
                    if format_kwargs:
                        try:
                            return base_path.format(**format_kwargs)
                        except (KeyError, ValueError):
                            # If format fails, return the template
                            return base_path
                    return base_path
    return None


def _is_valid_project_path(path: str) -> bool:
    """Check if a path is valid for a project dependency/output."""
    if not path:
        return False
    if path.startswith(("http://", "https://", "ftp://", "s3://", "gs://")):
        return False
    if os.path.isabs(path):
        return False
    if path.startswith(("/dev/", "/proc/", "/sys/", "~")):
        return False
    return True


def _detect_python_code_io(
    code: str,
    script_dir: str = ".",
    working_dir: str = ".",
    current_dir: str | None = None,
) -> dict[str, list[str]]:
    """Detect I/O from Python code string (used for notebook cells
    and scripts).

    Tracks os.chdir() calls and Jupyter %cd magic commands to maintain the
    effective working directory for resolving relative file paths. Supports
    variable tracking for paths defined in variables. All paths are normalized
    relative to the project root (current working directory).

    When analyzing notebook code, all cells should be concatenated
    into a single code string before calling this function. This
    ensures variable assignments defined in earlier cells are
    available for resolution in later cells.
    """
    inputs = []
    outputs = []
    current_dir = current_dir or working_dir
    import_dir = script_dir or "."
    # First pass: detect directory changes from %cd magic commands
    for line in code.split("\n"):
        stripped = line.strip()
        # Handle Jupyter %cd magic
        if stripped.startswith("%cd "):
            chdir_path = stripped[4:].strip()
            # Remove quotes if present
            chdir_path = chdir_path.strip("'\"")
            if chdir_path:
                current_dir = os.path.normpath(
                    os.path.join(current_dir, chdir_path)
                )
    # Remove Jupyter magic commands from code before parsing
    # (they are not valid Python syntax)
    code_for_parsing = "\n".join(
        line if not line.strip().startswith("%") else ""
        for line in code.split("\n")
    )

    try:
        tree = ast.parse(code_for_parsing)
    except SyntaxError:
        # If the code cannot be parsed, we cannot reliably detect directory
        # changes; keep the current working_dir unchanged.
        return {"inputs": inputs, "outputs": outputs}
    # Extract variable assignments for path tracking
    variables = _extract_variable_assignments(tree)
    # Second pass: identify all os.chdir() calls to track directory changes
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"
                    and node.func.attr == "chdir"
                    and len(node.args) >= 1
                ):
                    chdir_path = _resolve_variable_in_call(
                        node.args[0], variables
                    )
                    if chdir_path:
                        current_dir = os.path.normpath(
                            os.path.join(current_dir, chdir_path)
                        )

    # Helper to resolve a relative path back to project root
    def resolve_to_root(path: str) -> str:
        """Resolve a path from current_dir to project root."""
        full_path = os.path.normpath(os.path.join(current_dir, path))
        # Handle paths that reference parent directories
        # by computing the real path
        abs_path = os.path.abspath(full_path)
        project_root = os.path.abspath(working_dir)
        try:
            rel_path = os.path.relpath(abs_path, project_root)
        except ValueError:
            # If paths are on different drives (Windows), use normalized path
            rel_path = full_path
        # Always emit posix separators so downstream comparisons are stable
        # across platforms.
        rel_path = Path(rel_path).as_posix()
        # Strip leading ../ for paths outside project root
        while rel_path.startswith("../"):
            rel_path = rel_path[3:]
        return rel_path

    # Output methods for pandas-like objects
    output_methods = {
        "to_csv",
        "to_excel",
        "to_parquet",
        "to_feather",
        "to_pickle",
        "to_json",
        "to_hdf",
        "to_stata",
    }
    # Third pass: extract I/O operations using current_dir
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_file = _resolve_python_import(alias.name, import_dir)
                if local_file:
                    inputs.append(local_file)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                local_file = _resolve_python_import(node.module, import_dir)
                if local_file:
                    inputs.append(local_file)
            elif node.level > 0:
                parent_dir = import_dir
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
                    path = _resolve_variable_in_call(node.args[0], variables)
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
                        rel_path = resolve_to_root(path)
                        if "w" in mode or "a" in mode or "x" in mode:
                            outputs.append(rel_path)
                        else:
                            inputs.append(rel_path)
            elif isinstance(node.func, ast.Attribute):
                module = getattr(node.func.value, "id", None)
                if module and isinstance(module, str):
                    func = node.func.attr
                    if func in output_methods:
                        if len(node.args) >= 1:
                            path = _resolve_variable_in_call(
                                node.args[0], variables
                            )
                            if path:
                                outputs.append(resolve_to_root(path))
                        continue
                    if module == "pd" and func.startswith("read_"):
                        if len(node.args) >= 1:
                            path = _resolve_variable_in_call(
                                node.args[0], variables
                            )
                            if path:
                                inputs.append(resolve_to_root(path))
                    elif module in [
                        "df",
                        "data",
                        "frame",
                        "result",
                    ] and func.startswith("to_"):
                        if len(node.args) >= 1:
                            path = _resolve_variable_in_call(
                                node.args[0], variables
                            )
                            if path:
                                outputs.append(resolve_to_root(path))
                    elif module == "np" and func in [
                        "load",
                        "loadtxt",
                        "genfromtxt",
                        "fromfile",
                    ]:
                        if len(node.args) >= 1:
                            path = _resolve_variable_in_call(
                                node.args[0], variables
                            )
                            if path:
                                inputs.append(resolve_to_root(path))
                    elif module == "np" and func in [
                        "save",
                        "savetxt",
                        "savez",
                        "savez_compressed",
                    ]:
                        if len(node.args) >= 1:
                            path = _resolve_variable_in_call(
                                node.args[0], variables
                            )
                            if path:
                                outputs.append(resolve_to_root(path))
                    elif func == "savefig":
                        if len(node.args) >= 1:
                            path = _resolve_variable_in_call(
                                node.args[0], variables
                            )
                            if path:
                                outputs.append(resolve_to_root(path))
                # Handle chained method calls like ax.get_figure().savefig()
                # where node.func.value is itself a Call node
                elif isinstance(node.func.value, ast.Call):
                    func = node.func.attr
                    if func in output_methods:
                        if len(node.args) >= 1:
                            path = _resolve_variable_in_call(
                                node.args[0], variables
                            )
                            if path:
                                outputs.append(resolve_to_root(path))
                        continue
                    if func == "savefig":
                        if len(node.args) >= 1:
                            path = _resolve_variable_in_call(
                                node.args[0], variables
                            )
                            if path:
                                outputs.append(resolve_to_root(path))
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    return {"inputs": inputs, "outputs": outputs}


def _detect_julia_code_io(
    code: str, script_dir: str = "."
) -> dict[str, list[str]]:
    """Detect I/O from Julia code string (used for notebook cells)."""
    inputs = []
    outputs = []
    code = re.sub(r"#.*$", "", code, flags=re.MULTILINE)
    julia_vars = _extract_julia_string_assignments(code)
    include_pattern = r'include\s*\(\s*["\']([^"\']+\.jl)["\']\s*\)'
    include_matches = re.findall(include_pattern, code)
    for match in include_matches:
        if not os.path.isabs(match):
            full_path = os.path.join(script_dir, match)
            if os.path.exists(full_path):
                inputs.append(Path(os.path.relpath(full_path)).as_posix())
            elif _is_valid_project_path(match):
                inputs.append(match)
    read_patterns = [
        r'open\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))\s*,\s*["\']r["\']',
        r'open\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))\s*\)',
        r'CSV\.(?:read|File)\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
        r'readdlm\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
    ]
    write_patterns = [
        r'open\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))\s*,\s*["\']w["\']',
        r'CSV\.write\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
        r'writedlm\s*\(\s*(?:["\']([^"\']+)["\']|([A-Za-z_][A-Za-z0-9_]*))',
    ]
    for pattern in read_patterns:
        matches = re.findall(pattern, code)
        for match in matches:
            resolved = _resolve_julia_path_expr(match, julia_vars)
            if resolved:
                inputs.append(resolved)
    for pattern in write_patterns:
        matches = re.findall(pattern, code)
        for match in matches:
            resolved = _resolve_julia_path_expr(match, julia_vars)
            if resolved:
                outputs.append(resolved)
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
        return Path(os.path.relpath(file_path)).as_posix()
    init_path = os.path.join(search_dir, module_path, "__init__.py")
    if os.path.exists(init_path) and _is_valid_project_path(
        os.path.relpath(init_path)
    ):
        return Path(os.path.relpath(init_path)).as_posix()
    return None


def _detect_r_code_io(
    code: str,
    script_dir: str = ".",
    wdir: str = ".",
    project_root: str = ".",
    _seen: set[str] | None = None,
) -> dict[str, list[str]]:
    """Detect I/O from R code string (used for scripts and notebook cells).

    Parameters
    ----------
    code : str
        R code content to analyze.
    script_dir : str
        Directory containing the script (for resolving source() includes).
    wdir : str
        Working directory from which the script is executed (for data file paths).
    project_root : str
        Directory that ``here::here()`` resolves against, i.e. the project
        root where the pipeline runs.
    _seen : set[str] | None
        Absolute paths of scripts already analyzed, used to guard against
        cycles when recursing into ``source()``d scripts.

    Returns
    -------
    dict[str, list[str]]
        Dictionary with 'inputs' and 'outputs' keys.
    """
    inputs = []
    outputs = []
    if _seen is None:
        _seen = set()
    code = re.sub(r"#.*$", "", code, flags=re.MULTILINE)
    r_vars = _extract_r_string_assignments(code)
    fig_dir = r_vars.get("fig_dir")
    # A path argument may be a here::here()/file.path() call, a quoted literal,
    # or a variable name that resolves to one of those
    path_expr = (
        r'(here::here\([^)]*\)|file\.path\([^)]*\)|"[^"]+"|\'[^\']+\'|'
        r"[A-Za-z_][A-Za-z0-9_]*)"
    )
    # Detect source() calls for R script includes, add them as inputs, and
    # recurse into them so their I/O is attributed to this stage
    for raw in re.findall(r"source\s*\(\s*" + path_expr, code):
        resolved = _resolve_r_path_expr(raw, r_vars)
        if not resolved or not resolved.lower().endswith(".r"):
            continue
        if os.path.isabs(resolved):
            continue
        # here::here() paths are relative to the project root; everything else
        # is resolved relative to the sourcing script's directory
        if raw.strip().startswith("here::here"):
            fs_path = os.path.join(project_root, resolved)
        else:
            fs_path = os.path.join(script_dir, resolved)
        if os.path.exists(fs_path):
            inputs.append(Path(os.path.relpath(fs_path)).as_posix())
        elif _is_valid_project_path(resolved):
            inputs.append(resolved)
        # Recurse into the sourced script if we can read it
        abs_path = os.path.abspath(fs_path)
        if os.path.exists(fs_path) and abs_path not in _seen:
            _seen.add(abs_path)
            try:
                with open(fs_path, "r", encoding="utf-8") as f:
                    sub_code = f.read()
            except (OSError, UnicodeDecodeError):
                sub_code = None
            if sub_code is not None:
                sub_dir = (
                    os.path.dirname(Path(os.path.relpath(fs_path)).as_posix())
                    or "."
                )
                sub_io = _detect_r_code_io(
                    sub_code,
                    script_dir=sub_dir,
                    wdir=wdir,
                    project_root=project_root,
                    _seen=_seen,
                )
                inputs.extend(sub_io["inputs"])
                outputs.extend(sub_io["outputs"])
    # Read patterns that capture variables, here::here()/file.path()
    # expressions, or literals
    read_funcs = [
        r"read\.(?:csv|table|delim|tsv)",
        r"readRDS",
        r"readLines",
        r"load",
        r"read_csv",
        r"read_tsv",
        r"read_delim",
        r"read_excel",
        r"fread",
    ]
    for func in read_funcs:
        for match in re.findall(func + r"\s*\(\s*" + path_expr, code):
            resolved = _resolve_r_path_expr(match, r_vars)
            if resolved:
                inputs.append(resolved)
    # Write functions where the path is the second positional argument
    second_arg_write_funcs = [
        r"write\.(?:csv|table)",
        r"saveRDS",
        r"write_csv",
        r"write_tsv",
        r"write_delim",
        r"write_excel\w*",
        r"writeLines",
        r"fwrite",
    ]
    for func in second_arg_write_funcs:
        pattern = func + r"\s*\(\s*[^,]+,\s*" + path_expr
        for match in re.findall(pattern, code):
            resolved = _resolve_r_path_expr(match, r_vars)
            if resolved:
                outputs.append(resolved)
    # Write functions where the path is the (only) first positional argument
    first_arg_write_funcs = [
        r"ggsave",
        r"sink",
        r"pdf",
        r"png",
        r"svg",
        r"svglite",
        r"jpeg",
        r"tiff",
        r"bmp",
        r"cairo_pdf",
        r"CairoPNG",
        r"CairoPDF",
    ]
    for func in first_arg_write_funcs:
        pattern = func + r"\s*\(\s*" + path_expr
        for match in re.findall(pattern, code):
            resolved = _resolve_r_path_expr(match, r_vars)
            if resolved:
                outputs.append(resolved)
    # Write functions whose path is passed as a named argument, regardless of
    # position (e.g. saveRDS(x, file = ...), pdf(file = ...), save(file = ...))
    named_arg_write_funcs = [
        r"write\.(?:csv|table)",
        r"saveRDS",
        r"save",
        r"write_csv",
        r"write_tsv",
        r"write_delim",
        r"write_excel\w*",
        r"writeLines",
        r"fwrite",
        r"ggsave",
        r"sink",
        r"pdf",
        r"png",
        r"svg",
        r"svglite",
        r"jpeg",
        r"tiff",
        r"bmp",
        r"cairo_pdf",
        r"CairoPNG",
        r"CairoPDF",
    ]
    for func in named_arg_write_funcs:
        pattern = (
            func + r"\s*\([^)]*\b(?:file|filename|path|con)\s*=\s*" + path_expr
        )
        for match in re.findall(pattern, code):
            resolved = _resolve_r_path_expr(match, r_vars)
            if resolved:
                outputs.append(resolved)
    # save_fig() writes into fig_dir when the path isn't already qualified
    save_fig_patterns = [
        r"save_fig\s*\(\s*[^,]+,\s*" + path_expr,
        r"save_fig\s*\([^)]*filename\s*=\s*" + path_expr,
    ]
    for pattern in save_fig_patterns:
        for match in re.findall(pattern, code):
            resolved = _resolve_r_path_expr(match, r_vars)
            if resolved:
                if fig_dir and not os.path.isabs(resolved):
                    fig_dir_norm = fig_dir.rstrip("/\\")
                    if not resolved.startswith(
                        (fig_dir_norm + os.sep, fig_dir_norm + "/")
                    ):
                        resolved = os.path.join(fig_dir, resolved)
                outputs.append(resolved)
    inputs = [p for p in inputs if _is_valid_project_path(p)]
    outputs = [p for p in outputs if _is_valid_project_path(p)]
    # Resolve paths relative to working directory
    inputs = _resolve_paths_to_wdir(inputs, script_dir, wdir)
    outputs = _resolve_paths_to_wdir(outputs, script_dir, wdir)
    # Normalize to POSIX separators for persistence/display, since paths built
    # from here::here()/file.path() use the host OS separator
    inputs = [Path(p).as_posix() for p in inputs]
    outputs = [Path(p).as_posix() for p in outputs]
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    # A file produced within this stage is not an external input, even if it is
    # also read back (e.g. an intermediate written by one sourced script and
    # consumed by another)
    output_set = set(outputs)
    inputs = [p for p in inputs if p not in output_set]
    return {"inputs": inputs, "outputs": outputs}


def _extract_r_string_assignments(code: str) -> dict[str, str]:
    """Extract simple string assignments in R code.

    Captures both string-literal assignments (``x <- "path"``) and
    ``here::here()``/``file.path()`` assignments whose arguments are literals
    or previously assigned variables (``x <- here::here("a", "b")``).
    """
    assignments = {}
    pattern = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:<-|=)\s*[\"']([^\"']+)[\"']",
        flags=re.MULTILINE,
    )
    for name, value in pattern.findall(code):
        assignments[name] = value
    # Resolve here::here()/file.path() assignments using the literals above
    call_pattern = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:<-|=)\s*"
        r"(here::here\([^)]*\)|file\.path\([^)]*\))",
        flags=re.MULTILINE,
    )
    for name, expr in call_pattern.findall(code):
        resolved = _resolve_r_path_expr(expr, assignments)
        if resolved:
            assignments[name] = resolved
    return assignments


def _extract_r_string_vector_assignments(code: str) -> dict[str, list[str]]:
    """Extract character-vector assignments in R code.

    Captures assignments of the form ``x <- c("a", "b")`` so that a later
    ``pacman::p_load(char = x)`` can be resolved back to its package list.
    """
    assignments = {}
    pattern = re.compile(
        r"([A-Za-z_][A-Za-z0-9_.]*)\s*(?:<-|=)\s*c\(([^)]*)\)",
        flags=re.DOTALL,
    )
    for name, body in pattern.findall(code):
        strings = re.findall(r'["\']([a-zA-Z0-9._]+)["\']', body)
        if strings:
            assignments[name] = strings
    return assignments


def _resolve_r_package_args(
    call_args: str, vector_assignments: dict[str, list[str]]
) -> set[str]:
    """Resolve package names from a ``pacman::p_load()`` argument list.

    Handles quoted literals, inline ``c(...)`` vectors, bare (non-standard
    evaluation) names like ``p_load(dplyr, tidyr)``, and ``char = x`` where
    ``x`` is a character vector assigned earlier in the script.
    """
    packages = set()
    # Quoted strings are package names, whether passed directly or inside c()
    packages.update(re.findall(r'["\']([a-zA-Z0-9._]+)["\']', call_args))
    # char = <var> referencing a character-vector assignment
    for var in re.findall(r"char\s*=\s*([A-Za-z_][A-Za-z0-9_.]*)", call_args):
        packages.update(vector_assignments.get(var, []))
    # Bare names passed positionally; drop keyword arguments (install=, update=,
    # character.only=, etc.) and their values before collecting identifiers
    stripped = re.sub(r"[A-Za-z_][A-Za-z0-9_.]*\s*=\s*[^,]+", "", call_args)
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", stripped):
        # c() is the vector constructor, not a package; TRUE/FALSE are values
        if token not in {"c", "TRUE", "FALSE", "T", "F"}:
            packages.add(token)
    return packages


def _extract_julia_string_assignments(code: str) -> dict[str, str]:
    """Extract simple string assignments in Julia code."""
    assignments = {}
    pattern = re.compile(
        r"^\s*(?:const\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[\"']([^\"']+)[\"']",
        flags=re.MULTILINE,
    )
    for name, value in pattern.findall(code):
        assignments[name] = value
    return assignments


def _resolve_julia_path_expr(
    match: tuple[str, str] | str,
    variables: dict[str, str],
) -> str | None:
    """Resolve a Julia path expression from a regex match."""
    if isinstance(match, tuple):
        literal, var = match
        if literal:
            return literal
        if var:
            return variables.get(var)
        return None
    return variables.get(match) or match


def _resolve_r_path_expr(expr: str, variables: dict[str, str]) -> str | None:
    """Resolve simple R path expressions.

    Handles quoted literals, variables, and ``file.path()``/``here::here()``
    calls whose arguments are literals or known variables.
    """
    expr = expr.strip()
    if not expr:
        return None
    if expr[0] in ['"', "'"] and expr[-1] == expr[0]:
        return expr[1:-1]
    if expr in variables:
        return variables[expr]
    for prefix in ("file.path", "here::here"):
        if expr.startswith(prefix):
            match = re.match(re.escape(prefix) + r"\((.*)\)", expr)
            if not match:
                return None
            args = [a.strip() for a in match.group(1).split(",") if a.strip()]
            if not args:
                return None
            parts = []
            for arg in args:
                if arg[0] in ['"', "'"] and arg[-1] == arg[0]:
                    parts.append(arg[1:-1])
                elif arg in variables:
                    parts.append(variables[arg])
                else:
                    return None
            return os.path.join(*parts)
    return None


def generate_stage_name(cmd: list[str]) -> str:
    """Generate a stage name from a command.

    Parameters
    ----------
    cmd : list[str]
        The full command as a list of strings.

    Returns
    -------
    str
        The generated stage name.
    """
    if not cmd:
        return "stage"
    first_arg = cmd[0]
    # Check if first arg is a script/notebook file
    script_extensions = [
        ".py",
        ".jl",
        ".m",
        ".ipynb",
        ".tex",
        ".sh",
        ".bash",
        ".zsh",
        ".R",
    ]
    if any(first_arg.endswith(ext) for ext in script_extensions):
        # Extract base name from the script/notebook path
        base_name = os.path.splitext(os.path.basename(first_arg))[0]
        stage_name = base_name
    elif first_arg == "python" and len(cmd) > 1 and cmd[1].endswith(".py"):
        # Special handling for python script.py - use the script
        # filename as base
        script_path = cmd[1]
        base_name = os.path.splitext(os.path.basename(script_path))[0]
        stage_name = base_name
    elif first_arg == "julia" and len(cmd) > 1 and cmd[1].endswith(".jl"):
        # Special handling for julia script.jl - use the script
        # filename as base
        script_path = cmd[1]
        base_name = os.path.splitext(os.path.basename(script_path))[0]
        stage_name = base_name
    elif first_arg == "matlab" and len(cmd) > 1 and cmd[1].endswith(".m"):
        # Special handling for matlab script.m - use the script
        # filename as base
        script_path = cmd[1]
        base_name = os.path.splitext(os.path.basename(script_path))[0]
        stage_name = base_name
    elif first_arg == "Rscript" and len(cmd) > 1 and cmd[1].endswith(".R"):
        # Special handling for Rscript - use the script filename as base
        script_path = cmd[1]
        base_name = os.path.splitext(os.path.basename(script_path))[0]
        stage_name = base_name
    else:
        # For commands (like "echo", "matlab", "julia", etc.)
        # Use the command name as the base
        stage_name = first_arg
        # Shell interpreters should not include their arguments in the name
        # (as those often contain inline scripts with special characters)
        if first_arg not in ["bash", "sh", "zsh"] and len(cmd) > 1:
            # For MATLAB commands, filter out -batch flag
            remaining_args = cmd[1:]
            if first_arg == "matlab" and "-batch" in remaining_args:
                remaining_args = [
                    arg for arg in remaining_args if arg != "-batch"
                ]

            if remaining_args:
                args_part = "-".join(remaining_args)
                stage_name += "-" + args_part
    # Convert to kebab-case
    stage_name = stage_name.replace("_", "-").lower()
    # Replace dots with dashes (except file extensions which are
    # already stripped)
    stage_name = stage_name.replace(".", "-")
    # Replace spaces with dashes
    stage_name = stage_name.replace(" ", "-")
    # Remove parentheses, slashes and other special characters
    # (including shell redirects)
    stage_name = re.sub(r"[(){}\[\]'\"><|&;/]", "", stage_name)
    # Consolidate multiple dashes into single dashes
    stage_name = re.sub(r"-+", "-", stage_name)
    # Remove leading/trailing dashes
    stage_name = stage_name.strip("-")
    # If any args include the .ipynb extension, add a -notebook suffix
    if any(arg.endswith(".ipynb") for arg in cmd):
        stage_name += "-notebook"
    return stage_name


def detect_io(stage: dict) -> dict[str, list[str]]:
    """Detect inputs and outputs for a stage based on its kind.

    Parameters
    ----------
    stage : dict
        Stage configuration dictionary with 'kind', 'environment', and other
        stage-specific fields.

    Returns
    -------
    dict[str, list[str]]
        Dictionary with 'inputs' and 'outputs' keys containing detected paths.
    """
    from calkit.matlab import detect_matlab_command_io, detect_matlab_script_io

    stage_kind = stage.get("kind")
    script_path = (
        stage.get("script_path")
        or stage.get("notebook_path")
        or stage.get("target_path")
    )
    environment = stage.get("environment", "_system")
    wdir = stage.get("wdir")
    if stage_kind == "python-script" and script_path:
        return detect_python_script_io(script_path, wdir=wdir)
    elif stage_kind == "r-script" and script_path:
        return detect_r_script_io(script_path, wdir=wdir)
    elif stage_kind == "julia-script" and script_path:
        return detect_julia_script_io(script_path, wdir=wdir)
    elif stage_kind == "shell-script" and script_path:
        return detect_shell_script_io(script_path, wdir=wdir)
    elif stage_kind == "jupyter-notebook" and script_path:
        return detect_jupyter_notebook_io(script_path, wdir=wdir)
    elif stage_kind == "latex" and script_path:
        return detect_latex_io(script_path)
    elif stage_kind == "matlab-script" and script_path:
        return detect_matlab_script_io(
            script_path, environment=environment, wdir=wdir
        )
    elif stage_kind == "matlab-command":
        command = stage.get("command", "")
        wdir_str = wdir if wdir else "."
        return detect_matlab_command_io(
            command, environment=environment, wdir=wdir_str
        )
    elif stage_kind == "shell-command":
        command = stage.get("command", "")
        return detect_shell_command_io(command)
    # Return empty results for unsupported or unrecognized stage kinds
    return {"inputs": [], "outputs": []}


def _is_stdlib_module(module_name: str) -> bool:
    """Check if a module is part of the Python standard library."""
    # Get the base module name (before any dots)
    base_module = module_name.split(".")[0]

    # Known stdlib modules that might not be detected by other methods
    stdlib_modules = (
        set(sys.stdlib_module_names)
        if hasattr(sys, "stdlib_module_names")
        else set()
    )

    if base_module in stdlib_modules:
        return True

    # Additional check for common stdlib modules
    common_stdlib = {
        "os",
        "sys",
        "re",
        "json",
        "math",
        "datetime",
        "time",
        "random",
        "collections",
        "itertools",
        "functools",
        "pathlib",
        "subprocess",
        "typing",
        "io",
        "copy",
        "pickle",
        "csv",
        "sqlite3",
        "unittest",
        "logging",
        "argparse",
        "configparser",
        "email",
        "urllib",
        "http",
        "html",
        "xml",
        "hashlib",
        "base64",
        "tempfile",
        "shutil",
        "glob",
        "fnmatch",
        "contextlib",
        "abc",
        "dataclasses",
        "enum",
        "decimal",
        "fractions",
        "statistics",
        "platform",
        "socket",
        "ssl",
        "asyncio",
        "concurrent",
        "multiprocessing",
        "threading",
        "queue",
        "warnings",
    }

    return base_module in common_stdlib


def detect_python_dependencies(
    script_path: str | None = None,
    code: str | None = None,
) -> list[str]:
    """Detect non-stdlib dependencies from a Python script or code string.

    Parameters
    ----------
    script_path : str | None
        Path to Python script. Either this or code must be provided.
    code : str | None
        Python code string. Either this or script_path must be provided.

    Returns
    -------
    list[str]
        List of non-stdlib package names.
    """
    if script_path is None and code is None:
        raise ValueError("Either script_path or code must be provided")
    if code is None:
        assert script_path is not None  # Type guard
        if not os.path.exists(script_path):
            return []
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                code = f.read()
        except (UnicodeDecodeError, IOError):
            return []
    assert code is not None  # Type guard
    dependencies = set()
    # Strip IPython magic commands (line magics like %matplotlib and
    # cell magics like %%timeit) as they are not valid Python syntax
    lines = code.split("\n")
    cleaned_lines = []
    in_cell_magic = False
    for line in lines:
        stripped = line.strip()
        # Check for cell magic start (%%...)
        if stripped.startswith("%%"):
            in_cell_magic = True
            continue
        # If we're in a cell magic block, skip until we hit a blank line
        # or a line that doesn't look like it's part of the magic
        if in_cell_magic:
            if stripped == "" or not line.startswith((" ", "\t")):
                in_cell_magic = False
            else:
                continue
        # Skip line magics (%...)
        if stripped.startswith("%"):
            continue
        cleaned_lines.append(line)
    cleaned_code = "\n".join(cleaned_lines)
    try:
        tree = ast.parse(cleaned_code)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name
                if not _is_stdlib_module(module_name):
                    # Get the top-level package name
                    top_level = module_name.split(".")[0]
                    dependencies.add(top_level)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                module_name = node.module
                if not _is_stdlib_module(module_name):
                    top_level = module_name.split(".")[0]
                    dependencies.add(top_level)
    return sorted(list(dependencies))


def detect_r_dependencies(
    script_path: str | None = None,
    code: str | None = None,
) -> list[str]:
    """Detect package dependencies from an R script or code string.

    Parameters
    ----------
    script_path : str | None
        Path to R script. Either this or code must be provided.
    code : str | None
        R code string. Either this or script_path must be provided.

    Returns
    -------
    list[str]
        List of R package names.
    """
    if script_path is None and code is None:
        raise ValueError("Either script_path or code must be provided")
    if code is None:
        assert script_path is not None  # Type guard
        if not os.path.exists(script_path):
            return []
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                code = f.read()
        except (UnicodeDecodeError, IOError):
            return []
    assert code is not None  # Type guard
    dependencies = set()
    # Remove comments
    code = re.sub(r"#.*$", "", code, flags=re.MULTILINE)
    # Patterns for library() and require() calls
    patterns = [
        r'library\s*\(\s*["\']?([a-zA-Z0-9._]+)["\']?\s*\)',
        r'require\s*\(\s*["\']?([a-zA-Z0-9._]+)["\']?\s*\)',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, code)
        dependencies.update(matches)
    # requireNamespace()/loadNamespace() take the package as a string and are
    # commonly used to guard optional installs (e.g. pacman/here bootstrapping)
    dependencies.update(
        re.findall(
            r'(?:require|load)Namespace\s*\(\s*["\']([a-zA-Z0-9._]+)["\']',
            code,
        )
    )
    # Qualified calls like pkg::fn() or pkg:::fn() reference a package without
    # ever attaching it, so the package itself is still a dependency
    dependencies.update(re.findall(r"\b([a-zA-Z][a-zA-Z0-9._]*)\s*:::?", code))
    # pacman::p_load() loads (and optionally installs) packages dynamically; its
    # arguments may be bare names, quoted strings, or a character vector passed
    # via char=, possibly referencing a variable assigned earlier in the script
    vector_assignments = _extract_r_string_vector_assignments(code)
    for call_args in re.findall(
        r"p_load\s*\(((?:[^()]|\([^()]*\))*)\)", code, flags=re.DOTALL
    ):
        dependencies.update(
            _resolve_r_package_args(call_args, vector_assignments)
        )
    # Filter out base R packages
    base_packages = {
        "base",
        "compiler",
        "datasets",
        "graphics",
        "grDevices",
        "grid",
        "methods",
        "parallel",
        "splines",
        "stats",
        "stats4",
        "tcltk",
        "tools",
        "utils",
    }
    dependencies = {pkg for pkg in dependencies if pkg not in base_packages}
    return sorted(list(dependencies))


def detect_julia_dependencies(
    script_path: str | None = None,
    code: str | None = None,
) -> list[str]:
    """Detect package dependencies from a Julia script or code string.

    Parameters
    ----------
    script_path : str | None
        Path to Julia script. Either this or code must be provided.
    code : str | None
        Julia code string. Either this or script_path must be provided.

    Returns
    -------
    list[str]
        List of Julia package names.
    """
    if script_path is None and code is None:
        raise ValueError("Either script_path or code must be provided")
    if code is None:
        assert script_path is not None  # Type guard
        if not os.path.exists(script_path):
            return []
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                code = f.read()
        except (UnicodeDecodeError, IOError):
            return []
    assert code is not None  # Type guard
    dependencies = set()
    # Remove comments
    code = re.sub(r"#.*$", "", code, flags=re.MULTILINE)
    # Pattern for using statements
    pattern = r"using\s+([a-zA-Z0-9._]+)"
    matches = re.findall(pattern, code)
    dependencies.update(matches)
    return sorted(list(dependencies))


def detect_dependencies_from_notebook(
    notebook_path: str,
    language: NotebookLanguage | None = None,
) -> list[str]:
    """Detect dependencies from a Jupyter notebook.

    Parameters
    ----------
    notebook_path : str
        Path to the notebook.
    language : Literal["python", "julia", "r"] | None
        Language of the notebook. If None, will be detected from metadata.

    Returns
    -------
    list[str]
        List of package/module names.
    """
    if not os.path.exists(notebook_path):
        return []
    try:
        with open(notebook_path, "r", encoding="utf-8") as f:
            nb = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    # Detect language if not provided
    if language is None:
        detected = language_from_notebook(notebook_path, notebook=nb)
        language = detected if detected is not None else "python"
    # Collect all code from cells
    code_cells = [
        cell for cell in nb.get("cells", []) if cell.get("cell_type") == "code"
    ]
    all_code = []
    for cell in code_cells:
        source = cell.get("source", [])
        if isinstance(source, list):
            all_code.append("".join(source))
        else:
            all_code.append(source)
    combined_code = "\n".join(all_code)
    # Detect dependencies based on language
    if language == "python":
        return detect_python_dependencies(code=combined_code)
    elif language == "julia":
        return detect_julia_dependencies(code=combined_code)
    elif language == "r":
        return detect_r_dependencies(code=combined_code)
    return []


def create_python_requirements_file(
    dependencies: list[str],
    output_path: str,
) -> None:
    """Create a requirements.txt file from a list of dependencies.

    Parameters
    ----------
    dependencies : list[str]
        List of package names.
    output_path : str
        Path where the requirements.txt should be created.
    """
    from calkit.environments import create_python_requirements_content

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(create_python_requirements_content(dependencies))


def create_julia_project_file(
    dependencies: list[str],
    output_path: str,
    project_name: str = "environment",
) -> None:
    """Create a Julia Project.toml file from a list of dependencies.

    Parameters
    ----------
    dependencies : list[str]
        List of package names.
    output_path : str
        Path where the Project.toml should be created.
    project_name : str
        Name of the Julia project.
    """
    from calkit.environments import create_julia_project_file_content

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(create_julia_project_file_content(dependencies, project_name))


def create_r_description_file(
    dependencies: list[str],
    output_path: str,
) -> None:
    """Create a simple R DESCRIPTION file listing dependencies.

    This creates a minimal DESCRIPTION file that renv can work with.

    Parameters
    ----------
    dependencies : list[str]
        List of R package names.
    output_path : str
        Path where the DESCRIPTION should be created.
    """
    from calkit.environments import create_r_description_content

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(create_r_description_content(dependencies))


# Figure/dataset auto-detection
# A file is only treated as an auto-detected figure or dataset when it lives in
# a directory whose name signals its kind. These sets are intentionally narrow
# (and kept in sync with Calkit Cloud) so we don't flag arbitrary images or
# data files scattered around a repository.
FIGURE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".pdf",
    ".eps",
    ".tiff",
    ".tif",
}
FIGURE_DIRS = {"figures", "figure", "figs", "fig", "plots", "plot", "images"}
DATASET_EXTENSIONS = {
    ".csv",
    ".h5",
    ".hdf5",
    ".parquet",
    ".nc",
    ".zarr",
    ".feather",
    ".arrow",
    ".avro",
    ".json",
    ".jsonl",
    ".ndjson",
}
DATA_DIRS = {"data", "datasets", "dataset"}
RESULT_DIRS = {"results", "result"}
RESULT_EXTENSIONS = {
    ".json",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".parquet",
    ".h5",
    ".hdf5",
    ".txt",
    ".html",
}
PRESENTATION_DIRS = {"presentations", "presentation", "slides", "talks"}
PRESENTATION_EXTENSIONS = {".pdf", ".pptx", ".key"}
# Files that look like a presentation regardless of which directory they live in.
PRESENTATION_NAMES = {
    "slides.pdf",
    "slides.pptx",
    "slides.key",
    "presentation.pdf",
    "presentation.pptx",
    "presentation.key",
    "talk.pdf",
}

DETECTION_IGNORE_FPATH = os.path.join(".calkit", "ignore.json")


def load_detection_ignore(wdir: str | None = None) -> dict[str, dict]:
    """Load ``.calkit/ignore.json`` artifact detection exclusions.

    Returns an empty mapping when the file is absent. Raises ``ValueError`` when
    the file exists but is not valid JSON.
    """
    fpath = DETECTION_IGNORE_FPATH
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    if not os.path.isfile(fpath):
        return {}
    try:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {fpath}: {e}") from e
    if not isinstance(data, dict):
        return {}
    return data


def _is_excluded_from_kind(
    rel_path: str, kind: str, ignore: dict[str, dict]
) -> bool:
    """Whether ``rel_path`` must not be auto-detected as ``kind``."""
    entry = ignore.get(rel_path)
    if not isinstance(entry, dict):
        return False
    not_kinds = entry.get("not")
    if not isinstance(not_kinds, list):
        return False
    return kind in not_kinds


def _ancestor_dir_names(rel_path: str) -> set[str]:
    """Lower-cased names of the ancestor directories of a "/"-separated path."""
    return {p.lower() for p in rel_path.split("/")[:-1]}


def _path_ext(rel_path: str) -> str:
    name = rel_path.rsplit("/", 1)[-1]
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def is_figure_path(
    rel_path: str, *, ignore: dict[str, dict] | None = None
) -> bool:
    """Whether a repo-relative path looks like an auto-detectable figure."""
    if ignore and _is_excluded_from_kind(rel_path, "figure", ignore):
        return False
    ancestors = _ancestor_dir_names(rel_path)
    ext = _path_ext(rel_path)
    if ext in FIGURE_EXTENSIONS and ancestors & FIGURE_DIRS:
        return True
    # A Plotly figure is stored as JSON; treat .json under a figure-only
    # directory (one that isn't also a data directory) as a figure.
    if ext == ".json" and ancestors & (FIGURE_DIRS - DATA_DIRS):
        return True
    return False


def is_dataset_path(
    rel_path: str, *, ignore: dict[str, dict] | None = None
) -> bool:
    """Whether a repo-relative path looks like an auto-detectable dataset."""
    if ignore and _is_excluded_from_kind(rel_path, "dataset", ignore):
        return False
    return (
        _path_ext(rel_path) in DATASET_EXTENSIONS
        and bool(_ancestor_dir_names(rel_path) & DATA_DIRS)
        and not is_figure_path(rel_path, ignore=ignore)
    )


def is_result_path(
    rel_path: str, *, ignore: dict[str, dict] | None = None
) -> bool:
    """Whether a repo-relative path looks like an auto-detectable result.

    A result is a data-like file (JSON, CSV, etc.) under a ``results``-style
    directory. Anything already detected as a figure or dataset is excluded.
    """
    if ignore and _is_excluded_from_kind(rel_path, "result", ignore):
        return False
    return (
        _path_ext(rel_path) in RESULT_EXTENSIONS
        and bool(_ancestor_dir_names(rel_path) & RESULT_DIRS)
        and not is_figure_path(rel_path, ignore=ignore)
        and not is_dataset_path(rel_path, ignore=ignore)
    )


def is_presentation_path(
    rel_path: str, *, ignore: dict[str, dict] | None = None
) -> bool:
    """Whether a repo-relative path looks like an auto-detectable presentation.

    Either a slide-deck file (PDF/PPTX/KEY) under a ``slides``/``presentations``
    directory, or a file with a presentation-like name (e.g. ``slides.pdf``,
    ``presentation.pdf``) anywhere. Figures are excluded.
    """
    if ignore and _is_excluded_from_kind(rel_path, "presentation", ignore):
        return False
    if is_figure_path(rel_path, ignore=ignore):
        return False
    name = rel_path.rsplit("/", 1)[-1].lower()
    if name in PRESENTATION_NAMES:
        return True
    return _path_ext(rel_path) in PRESENTATION_EXTENSIONS and bool(
        _ancestor_dir_names(rel_path) & PRESENTATION_DIRS
    )


PUBLICATION_DIRS = {
    "publication",
    "publications",
    "paper",
    "papers",
    "manuscript",
    "manuscripts",
    "thesis",
    "report",
    "reports",
    "pub",
    "pubs",
}
PUBLICATION_EXTENSIONS = {".pdf", ".tex", ".docx"}
# Files that look like a publication regardless of which directory they live in.
PUBLICATION_NAMES = {
    "paper.pdf",
    "manuscript.pdf",
    "thesis.pdf",
    "report.pdf",
    "paper.tex",
    "main.tex",
    "manuscript.tex",
    "thesis.tex",
}


def is_publication_path(
    rel_path: str, *, ignore: dict[str, dict] | None = None
) -> bool:
    """Whether a repo-relative path looks like an auto-detectable publication.

    Either a document (PDF/TeX/DOCX) under a ``paper``/``publication``/
    ``thesis``-style directory, or a file with a publication-like name (e.g.
    ``manuscript.pdf``, ``main.tex``) anywhere. Figures and presentations are
    excluded.
    """
    if ignore and _is_excluded_from_kind(rel_path, "publication", ignore):
        return False
    if is_figure_path(rel_path, ignore=ignore) or is_presentation_path(
        rel_path, ignore=ignore
    ):
        return False
    name = rel_path.rsplit("/", 1)[-1].lower()
    if name in PUBLICATION_NAMES:
        return True
    return _path_ext(rel_path) in PUBLICATION_EXTENSIONS and bool(
        _ancestor_dir_names(rel_path) & PUBLICATION_DIRS
    )


def detect_artifact_kind(
    rel_path: str, *, ignore: dict[str, dict] | None = None
) -> str | None:
    """Infer an artifact's release kind from its repo-relative path.

    Returns one of ``"figure"``, ``"presentation"``, ``"publication"``, or
    ``"dataset"``, or ``None`` if the path doesn't look like any of these.
    """
    if is_figure_path(rel_path, ignore=ignore):
        return "figure"
    if is_presentation_path(rel_path, ignore=ignore):
        return "presentation"
    if is_publication_path(rel_path, ignore=ignore):
        return "publication"
    if is_dataset_path(rel_path, ignore=ignore):
        return "dataset"
    return None


def _is_hidden_path(rel_path: str) -> bool:
    return any(part.startswith(".") for part in rel_path.split("/"))


def _is_under_any_dir(rel_path: str, dirs: list[str]) -> bool:
    """Whether ``rel_path`` equals or lives inside any of ``dirs``."""
    return any(rel_path == d or rel_path.startswith(d + "/") for d in dirs)


def _collapse_dataset_folders(paths: list[str]) -> list[str]:
    """Collapse data files into their containing folder.

    A folder holding two or more data files is reported as a single dataset
    rather than file-by-file. Folders nested inside another collapsed folder
    are dropped so only the outermost dataset folder remains.
    """
    by_dir: dict[str, list[str]] = {}
    for p in paths:
        directory = p.rsplit("/", 1)[0] if "/" in p else ""
        by_dir.setdefault(directory, []).append(p)
    collapsed: set[str] = set()
    for directory, group in by_dir.items():
        if directory and len(group) >= 2:
            collapsed.add(directory)
        else:
            collapsed.update(group)
    result = sorted(collapsed)
    return [
        p
        for p in result
        if not any(o != p and p.startswith(o + "/") for o in result)
    ]


def detect_figures(
    candidate_paths: list[str],
    reserved_paths: list[str] | tuple[str, ...] = (),
    ignore: dict[str, dict] | None = None,
) -> list[str]:
    """Auto-detected figure paths among ``candidate_paths``.

    Paths under a dot-directory or under one of ``reserved_paths`` (declared
    artifacts and pipeline outputs) are skipped.
    """
    reserved = list(reserved_paths)
    return sorted(
        {
            p
            for p in candidate_paths
            if not _is_hidden_path(p)
            and not _is_under_any_dir(p, reserved)
            and is_figure_path(p, ignore=ignore)
        }
    )


def detect_datasets(
    candidate_paths: list[str],
    reserved_paths: list[str] | tuple[str, ...] = (),
    figure_paths: list[str] | tuple[str, ...] = (),
    ignore: dict[str, dict] | None = None,
) -> list[str]:
    """Auto-detected dataset paths among ``candidate_paths``.

    Anything already detected as a figure (``figure_paths``) is excluded, and a
    folder full of data files collapses to a single dataset entry.
    """
    reserved = list(reserved_paths)
    figset = set(figure_paths)
    files = {
        p
        for p in candidate_paths
        if not _is_hidden_path(p)
        and not _is_under_any_dir(p, reserved)
        and p not in figset
        and is_dataset_path(p, ignore=ignore)
    }
    return _collapse_dataset_folders(sorted(files))


def detect_results(
    candidate_paths: list[str],
    reserved_paths: list[str] | tuple[str, ...] = (),
    ignore: dict[str, dict] | None = None,
) -> list[str]:
    """Auto-detected result paths among ``candidate_paths``.

    Paths under a dot-directory or under one of ``reserved_paths`` (declared
    artifacts) are skipped.
    """
    reserved = list(reserved_paths)
    return sorted(
        {
            p
            for p in candidate_paths
            if not _is_hidden_path(p)
            and not _is_under_any_dir(p, reserved)
            and is_result_path(p, ignore=ignore)
        }
    )


def detect_presentations(
    candidate_paths: list[str],
    reserved_paths: list[str] | tuple[str, ...] = (),
    ignore: dict[str, dict] | None = None,
) -> list[str]:
    """Auto-detected presentation paths among ``candidate_paths``."""
    reserved = list(reserved_paths)
    return sorted(
        {
            p
            for p in candidate_paths
            if not _is_hidden_path(p)
            and not _is_under_any_dir(p, reserved)
            and is_presentation_path(p, ignore=ignore)
        }
    )


def list_repo_files(wdir: str | None = None) -> list[str]:
    """Repo-relative paths of files Git does not ignore.

    Combines tracked and untracked files while honoring ``.gitignore``, so
    detection skips virtualenvs, ``node_modules``, and other ignored content.
    Paths are returned relative to ``wdir`` (or the current directory), using
    POSIX separators; files outside ``wdir`` are omitted.
    """
    import calkit.git

    try:
        repo = calkit.git.get_repo(wdir)
    except Exception:
        return []
    files = calkit.git.ls_files(
        repo, "--cached", "--others", "--exclude-standard"
    )
    repo_root = repo.working_dir
    base = os.path.abspath(wdir if wdir is not None else ".")
    rel_files = []
    for f in files:
        rel = os.path.relpath(os.path.join(repo_root, f), base)
        if rel.startswith(".."):
            continue
        rel_files.append(Path(rel).as_posix())
    return rel_files


def list_dvc_tracked_files(wdir: str | None = None) -> list[str]:
    """Repo-relative paths of files tracked by DVC.

    DVC-tracked artifacts (added via ``dvc add`` or produced as pipeline
    outputs) are Git-ignored, so they don't appear in :func:`list_repo_files`;
    include them so figures and datasets stored with DVC are still detected.
    Returns an empty list when DVC isn't available or the project isn't a DVC
    repo.
    """
    from calkit.dvc.core import list_paths

    try:
        return [
            p.replace("\\", "/")
            for p in list_paths(wdir=wdir, recursive=True)
            if p
        ]
    except Exception:
        return []


def _reserved_artifact_paths(
    wdir: str | None = None, ck_info: dict | None = None
) -> list[str]:
    """Paths of artifacts declared in ``calkit.yaml``.

    These are excluded from auto-detection so a declared figure/dataset isn't
    reported twice and individual files inside a declared artifact folder aren't
    listed separately. Pipeline/DVC stage outputs are intentionally *not*
    reserved: a figure or dataset produced by the pipeline should still be
    detected (and shown with its producing stage as provenance).
    """
    import calkit

    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    paths: list[str] = []
    for kind in ("figures", "datasets", "results", "presentations"):
        for obj in ck_info.get(kind, []) or []:
            if isinstance(obj, dict) and isinstance(obj.get("path"), str):
                paths.append(obj["path"])
    return [p.replace("\\", "/") for p in paths]


def detect_project_artifacts(
    wdir: str | None = None, ck_info: dict | None = None
) -> dict[str, list[str]]:
    """Auto-detect figure and dataset paths in the project at ``wdir``.

    Candidates are the files Git does not ignore plus any files tracked by DVC
    (which are Git-ignored); declared artifacts are reserved so they aren't
    detected again.
    """
    import calkit

    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    ignore = load_detection_ignore(wdir=wdir)
    reserved = _reserved_artifact_paths(wdir=wdir, ck_info=ck_info)
    candidates = list(
        dict.fromkeys(
            [*list_repo_files(wdir=wdir), *list_dvc_tracked_files(wdir=wdir)]
        )
    )
    figures = detect_figures(
        candidates, reserved_paths=reserved, ignore=ignore
    )
    datasets = detect_datasets(
        candidates,
        reserved_paths=reserved,
        figure_paths=figures,
        ignore=ignore,
    )
    results = detect_results(
        candidates, reserved_paths=reserved, ignore=ignore
    )
    presentations = detect_presentations(
        candidates, reserved_paths=reserved, ignore=ignore
    )
    return {
        "figures": figures,
        "datasets": datasets,
        "results": results,
        "presentations": presentations,
    }
