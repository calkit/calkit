"""Functionality for working with MATLAB."""

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

DOCKERFILE_TEMPLATE = r"""
# Copyright 2023-2025 The MathWorks, Inc.

# To specify which MATLAB release to install in the container, edit the value of the MATLAB_RELEASE argument.
# Use uppercase to specify the release, for example: ARG MATLAB_RELEASE=R2021b
ARG MATLAB_RELEASE={matlab_version}

# Specify the extra products to install into the image. These products can either be toolboxes or support packages.
# This is a space delimited list with each product having underscores and capitalized names
ARG ADDITIONAL_PRODUCTS="{additional_products}"

# This Dockerfile builds on the Ubuntu-based mathworks/matlab image.
# To check the available matlab images, see: https://hub.docker.com/r/mathworks/matlab
FROM mathworks/matlab:$MATLAB_RELEASE

# Declare the global argument to use at the current build stage
ARG MATLAB_RELEASE
ARG ADDITIONAL_PRODUCTS

# By default, the MATLAB container runs as user "matlab". To install mpm dependencies, switch to root.
USER root

# Install mpm dependencies
RUN export DEBIAN_FRONTEND=noninteractive \
    && apt-get update \
    && apt-get install --no-install-recommends --yes \
        wget \
        ca-certificates \
    && apt-get clean \
    && apt-get autoremove \
    && rm -rf /var/lib/apt/lists/*

# Run mpm to install MathWorks products into the existing MATLAB installation directory,
# and delete the mpm installation afterwards.
# Modify it by setting the ADDITIONAL_PRODUCTS defined above,
# e.g. ADDITIONAL_PRODUCTS="Statistics_and_Machine_Learning_Toolbox Parallel_Computing_Toolbox MATLAB_Coder".
# If mpm fails to install successfully then output the logfile to the terminal, otherwise cleanup.

# Switch to user matlab, and pass in $HOME variable to mpm,
# so that mpm can set the correct root folder for the support packages.
{additional_products_block}

# When running the container a license file can be mounted,
# or a license server can be provided as an environment variable.
# For more information, see https://hub.docker.com/r/mathworks/matlab

# Alternatively, you can provide a license server to use
# with the docker image while building the image.
# Specify the host and port of the machine that serves the network licenses
# if you want to bind in the license info as an environment variable.
# You can also build with something like --build-arg LICENSE_SERVER=27000@MyServerName,
# in which case you should uncomment the following two lines.
# If these lines are uncommented, $LICENSE_SERVER must be a valid license
# server or browser mode will not start successfully.
# ARG LICENSE_SERVER
# ENV MLM_LICENSE_FILE=$LICENSE_SERVER

# The following environment variables allow MathWorks to understand how this MathWorks
# product is being used. This information helps us make MATLAB even better.
# Your content, and information about the content within your files, is not shared with MathWorks.
# To opt out of this service, delete the environment variables defined in the following line.
# See the Help Make MATLAB Even Better section in the accompanying README to learn more:
# https://github.com/mathworks-ref-arch/matlab-dockerfile#help-make-matlab-even-better
ENV MW_DDUX_FORCE_ENABLE=true MW_CONTEXT_TAGS=$MW_CONTEXT_TAGS,MATLAB:TOOLBOXES:DOCKERFILE:V1

WORKDIR /home/matlab
# Inherit ENTRYPOINT and CMD from base image.
""".strip()

ADDITIONAL_PRODUCTS_BLOCK = r"""
WORKDIR /tmp
USER matlab
RUN wget -q https://www.mathworks.com/mpm/glnxa64/mpm \
    && chmod +x mpm \
    && EXISTING_MATLAB_LOCATION=$(dirname $(dirname $(readlink -f $(which matlab)))) \
    && sudo HOME=${HOME} ./mpm install \
        --destination=${EXISTING_MATLAB_LOCATION} \
        --release=${MATLAB_RELEASE} \
        --products ${ADDITIONAL_PRODUCTS} \
    || (echo "MPM Installation Failure. See below for more information:" && cat /tmp/mathworks_root.log && false) \
    && sudo rm -rf mpm /tmp/mathworks_root.log
"""


def create_dockerfile(
    matlab_version: Literal["R2023a", "R2023b", "R2024a", "R2024b", "R2025a"],
    additional_products: list[
        Literal["Simulink", "5G_Toolbox", "Simscape"]
    ] = [],
    write: bool = True,
    fpath_out: str = "Dockerfile",
) -> str:
    additional_products_txt = " ".join(additional_products)
    if additional_products:
        additional_products_block = ADDITIONAL_PRODUCTS_BLOCK
    else:
        additional_products_block = ""
    dockerfile_txt = DOCKERFILE_TEMPLATE.format(
        matlab_version=matlab_version,
        additional_products=additional_products_txt,
        additional_products_block=additional_products_block,
    )
    if write:
        with open(fpath_out, "w") as f:
            f.write(dockerfile_txt)
    return dockerfile_txt


def get_docker_image_name(ck_info: dict, env_name: str) -> str:
    env = ck_info["environments"][env_name]
    products = env.get("products", [])
    version = env.get("version")
    # Compute MD5 hash of products list to create a unique image tag
    products_md5 = hashlib.md5(
        " ".join(sorted(products)).encode("utf-8")
    ).hexdigest()[:8]
    return f"matlab:{version.lower()}-{products_md5}"


def _is_valid_project_path(path: str) -> bool:
    """Check if a path is valid for the project (no traversal,
    not absolute, not URL).
    """
    # Use the same validation as in calkit.detect to ensure consistency
    if not path or not path.strip():
        return False
    # Reject any URI-like scheme (http, https, ftp, s3, gs, etc.)
    if path.startswith(("http://", "https://", "ftp://", "s3://", "gs://")):
        return False
    # Reject absolute filesystem paths
    if os.path.isabs(path):
        return False
    # Reject special system paths
    if path.startswith(("/dev/", "/proc/", "/sys/", "~")):
        return False
    # Reject any path traversal via ..
    if ".." in path:
        return False
    return True


def _extract_matlab_string_assignments(code: str) -> dict[str, str]:
    """Extract simple string variable assignments from MATLAB code.

    Returns a dict mapping variable names to their string values.
    Only tracks direct assignments like: var = 'path/to/file'
    or var = fullfile('dir', 'file')
    """
    assignments = {}
    # Pattern for simple string assignments
    # Matches: varname = 'string' or varname = "string"
    pattern = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"](.*?)['\"]",
        flags=re.MULTILINE,
    )
    for name, value in pattern.findall(code):
        assignments[name] = value
    # Also extract fullfile() assignments
    # Matches: varname = fullfile(...)
    fullfile_pattern = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(fullfile\s*\([^)]+\))",
        flags=re.MULTILINE,
    )
    for name, fullfile_expr in fullfile_pattern.findall(code):
        resolved = _resolve_fullfile_expr(fullfile_expr, assignments)
        if resolved:
            assignments[name] = resolved
    return assignments


def _resolve_fullfile_expr(expr: str, variables: dict[str, str]) -> str | None:
    """Resolve a fullfile() expression to a path string.

    Handles: fullfile('dir', 'subdir', 'file.txt')
    or: fullfile(var, 'file.txt')

    Parameters
    ----------
    expr : str
        The fullfile expression (e.g., "fullfile('data', 'raw.csv')")
    variables : dict[str, str]
        Dictionary of known variable assignments

    Returns
    -------
    str | None
        Resolved path or None if unable to resolve
    """
    # Extract arguments from fullfile(...)
    match = re.match(r"fullfile\s*\((.*)\)", expr.strip())
    if not match:
        return None
    args_str = match.group(1)
    # Split by comma, but need to be careful with nested calls
    # Simple approach: split by comma and handle string literals
    parts = []
    current = ""
    in_string = False
    string_char = None
    paren_depth = 0
    for char in args_str:
        if char in ["'", '"'] and not in_string:
            in_string = True
            string_char = char
        elif char == string_char and in_string:
            in_string = False
            string_char = None
        elif char == "(" and not in_string:
            paren_depth += 1
        elif char == ")" and not in_string:
            paren_depth -= 1
        elif char == "," and not in_string and paren_depth == 0:
            parts.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        parts.append(current.strip())
    # Resolve each part
    resolved_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # String literal
        if (part[0] in ["'", '"']) and (part[-1] == part[0]):
            resolved_parts.append(part[1:-1])
        # Variable reference
        elif part in variables:
            resolved_parts.append(variables[part])
        else:
            # Can't resolve this part, give up
            return None
    if not resolved_parts:
        return None
    # Join with os.path.join
    return os.path.join(*resolved_parts)


def _resolve_matlab_path_expr(
    expr: str, variables: dict[str, str]
) -> str | None:
    """Resolve a MATLAB path expression from a regex match.

    Handles:
    - Literal strings: 'file.csv' or "file.csv"
    - Variable references: raw_path
    - fullfile() expressions: fullfile('data', 'file.csv')
    """
    expr = expr.strip()
    if not expr:
        return None
    # fullfile() expression
    if expr.startswith("fullfile"):
        return _resolve_fullfile_expr(expr, variables)
    # Literal string
    if (expr[0] in ["'", '"']) and (expr[-1] == expr[0]):
        return expr[1:-1]
    # Variable reference
    if expr in variables:
        return variables[expr]
    return None


def _detect_matlab_io_static(
    content: str, script_dir: str = ".", wdir: str = "."
) -> dict[str, list[str]]:
    """Detect inputs and outputs from MATLAB code using static analysis.

    Parameters
    ----------
    content : str
        MATLAB code content to analyze
    script_dir : str
        Directory containing the script (for resolving relative paths)
    wdir : str
        Working directory from which the script will be executed

    Returns
    -------
    dict
        Dictionary with 'inputs' and 'outputs' keys containing detected paths
    """
    inputs = []
    outputs = []
    # Remove block comments (%{ ... %}) first, before removing line comments
    content = re.sub(r"%\{.*?%\}", "", content, flags=re.DOTALL)
    # Then remove MATLAB line comments (% to end of line)
    content = re.sub(r"%.*$", "", content, flags=re.MULTILINE)
    # Extract variable assignments for path tracking
    matlab_vars = _extract_matlab_string_assignments(content)
    # Detect function/script calls (potential dependencies)
    # Look for calls like: functionName(...) or run('script.m')
    run_pattern = r"run\s*\(\s*['\"]([^'\"]+\.m)['\"]\s*\)"
    run_matches = re.findall(run_pattern, content)
    for match in run_matches:
        if not os.path.isabs(match):
            full_path = os.path.join(script_dir, match)
            if os.path.exists(full_path):
                rel_path = os.path.relpath(full_path)
                # Convert to POSIX format for cross-platform compatibility
                inputs.append(Path(rel_path).as_posix())
            elif _is_valid_project_path(match):
                inputs.append(match)
    # Detect input file operations - now supporting variables and fullfile()
    # These patterns capture literals, variables, or fullfile() expressions
    read_patterns = [
        r"load\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"readtable\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"readmatrix\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"readcell\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"csvread\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"xlsread\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"fopen\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*,\s*['\"]r",
        r"imread\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"audioread\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"VideoReader\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"parquetread\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"h5read\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*,",
    ]
    # Process read patterns with variable resolution
    for pattern in read_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            resolved = _resolve_matlab_path_expr(match, matlab_vars)
            if resolved:
                inputs.append(resolved)
    # Detect output file operations, supporting variables and fullfile()
    write_patterns = [
        r"save\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"writetable\s*\(\s*[^,]+,\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"writematrix\s*\(\s*[^,]+,\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"writecell\s*\(\s*[^,]+,\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"csvwrite\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*,",
        r"xlswrite\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*,",
        r"fopen\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*,\s*['\"]w",
        r"imwrite\s*\(\s*[^,]+,\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"audiowrite\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*,",
        r"VideoWriter\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"parquetwrite\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*,",
        r"parquetwrite\s*\(\s*[^,]+,\s*(['\"]([^'\"]+)['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"h5write\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*,",
        r"h5create\s*\(\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*,",
    ]
    # Graphics output patterns, supporting variables and fullfile()
    graphics_patterns = [
        r"saveas\s*\([^,]+,\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"print\s*\([^,]*,\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"exportgraphics\s*\([^,]+,\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
        r"savefig\s*\([^,]*,\s*(['\"][^'\"]+['\"]|fullfile\s*\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
    ]
    # Process write and graphics patterns with variable resolution
    for pattern in write_patterns + graphics_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            # Handle tuple matches from nested groups
            if isinstance(match, tuple):
                match = (
                    match[0]
                    if match[0]
                    else (match[1] if len(match) > 1 else "")
                )
            resolved = _resolve_matlab_path_expr(match, matlab_vars)
            if resolved:
                outputs.append(resolved)
    # Filter out invalid paths and normalize relative paths
    cwd = os.path.abspath(wdir)

    def normalize_project_path(path: str) -> str | None:
        if not path or not path.strip():
            return None
        if path.startswith(
            ("http://", "https://", "ftp://", "s3://", "gs://")
        ):
            return None
        if os.path.isabs(path) or path.startswith(
            ("/dev/", "/proc/", "/sys/", "~")
        ):
            return None
        # MATLAB paths are relative to the script directory, not wdir
        # (since that's where MATLAB interprets relative paths from)
        normalized = os.path.normpath(os.path.join(script_dir, path))
        normalized_abs = os.path.abspath(normalized)
        try:
            common = os.path.commonpath([cwd, normalized_abs])
        except ValueError:
            return None
        if common != cwd:
            return None
        try:
            normalized_rel = os.path.relpath(normalized_abs, cwd)
        except ValueError:
            normalized_rel = normalized
        return Path(normalized_rel).as_posix()

    normalized_inputs = []
    for p in inputs:
        normalized = normalize_project_path(p)
        if normalized is not None:
            normalized_inputs.append(normalized)
    normalized_outputs = []
    for p in outputs:
        normalized = normalize_project_path(p)
        if normalized is not None:
            normalized_outputs.append(normalized)
    # Remove duplicates while preserving order
    inputs = list(dict.fromkeys(normalized_inputs))
    outputs = list(dict.fromkeys(normalized_outputs))
    return {"inputs": inputs, "outputs": outputs}


def get_deps_from_matlab(
    filepath: str, environment: str = "_system"
) -> list[str]:
    """Automatically get dependencies from MATLAB.

    Uses MATLAB's requiredFilesAndProducts to discover dependencies.
    If MATLAB cannot be invoked or returns an error, falls back to
    static analysis.

    Parameters
    ----------
    filepath : str
        Path to the MATLAB file (.m) to analyze
    environment : str
        Environment name to use for running MATLAB. Default is "_system".

    Returns
    -------
    list[str]
        List of dependency file paths in POSIX format.
    """
    # Build command as a list to avoid shell injection
    cmd_list = []
    if environment != "_system":
        cmd_list.extend(
            ["calkit", "xenv", "-n", environment, "--no-check", "--"]
        )
    cmd_list.append("matlab")
    cmd_list.append("-batch")
    # Quote the filepath for MATLAB and escape single quotes
    quoted = filepath.replace("'", "''")
    # MATLAB code that adds the current folder to path and
    # prints required files for the given file. Use disp to ensure
    # newline-separated output.
    matlab_code = (
        "addpath(genpath(pwd)); "
        f"f = matlab.codetools.requiredFilesAndProducts('{quoted}'); "
        "for i=1:numel(f); disp(f{i}); end"
    )
    cmd_list.append(matlab_code)
    try:
        result = subprocess.run(
            cmd_list, capture_output=True, text=True, timeout=120
        )
    except (subprocess.TimeoutExpired, Exception):
        # If subprocess fails to start or times out, fall back to
        # static analysis
        return _get_deps_from_matlab_static(filepath)
    if result.returncode != 0:
        # MATLAB call failed; fall back to static analysis
        return _get_deps_from_matlab_static(filepath)
    if not result.stdout.strip():
        # No output from MATLAB; fall back to static analysis
        return _get_deps_from_matlab_static(filepath)
    abs_paths = [
        p.strip() for p in result.stdout.strip().splitlines() if p.strip()
    ]
    rel_paths: list[str] = []
    for p in abs_paths:
        try:
            # Convert to a path relative to the current working dir
            rel = os.path.relpath(p)
        except Exception:
            # If any issue, skip this path
            continue
        # Convert to POSIX-style path for DVC compatibility
        rel_posix = Path(rel).as_posix()
        if rel_posix not in rel_paths:
            rel_paths.append(rel_posix)
    # Remove the target file itself from dependencies
    fp_posix = Path(filepath).as_posix()
    return [p for p in rel_paths if p != fp_posix]


def _get_deps_from_matlab_static(filepath: str) -> list[str]:
    """Get dependencies using static analysis as fallback.

    Parameters
    ----------
    filepath : str
        Path to the MATLAB file to analyze

    Returns
    -------
    list[str]
        List of dependency file paths
    """
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, IOError):
        return []
    script_dir = os.path.dirname(filepath) if filepath else "."
    # For static fallback, assume script is run from current directory
    io_info = _detect_matlab_io_static(content, script_dir, wdir=".")
    # Dependencies are the inputs detected by static analysis
    return io_info["inputs"].copy()


def detect_matlab_script_io(
    script_path: str, environment: str = "_system", wdir: str | None = None
) -> dict[str, list[str]]:
    """Detect inputs and outputs for a MATLAB script.

    Tries to use MATLAB's requiredFilesAndProducts to detect script
    dependencies. Falls back to static analysis if MATLAB is
    unavailable or fails.

    Parameters
    ----------
    script_path : str
        Path to the MATLAB script (.m file)
    environment : str
        Environment name to use for running MATLAB. Default is "_system".
    wdir : str | None
        Working directory from which the script will be executed.

    Returns
    -------
    dict
        Dictionary with 'inputs' and 'outputs' keys containing detected file paths.
    """
    # Get .m file dependencies from MATLAB's requiredFilesAndProducts
    matlab_deps = get_deps_from_matlab(script_path, environment)
    # Also use static analysis to detect data file I/O
    # (requiredFilesAndProducts only detects .m files, not data files)
    if not os.path.exists(script_path):
        static_inputs = []
        outputs = []
    else:
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                content = f.read()
            script_dir = os.path.dirname(script_path) if script_path else "."
            effective_wdir = wdir or "."
            io_info = _detect_matlab_io_static(
                content, script_dir, wdir=effective_wdir
            )
            static_inputs = io_info["inputs"]
            outputs = io_info["outputs"]
        except (UnicodeDecodeError, IOError):
            static_inputs = []
            outputs = []
    # Combine MATLAB dependencies with static inputs and remove duplicates
    all_inputs = matlab_deps + static_inputs
    inputs = list(
        dict.fromkeys(all_inputs)
    )  # Remove duplicates, preserve order
    return {"inputs": inputs, "outputs": outputs}


def detect_matlab_command_io(
    command: str, environment: str = "_system", wdir: str | None = None
) -> dict[str, list[str]]:
    """Detect inputs and outputs for a MATLAB command.

    Tries to use MATLAB's requiredFilesAndProducts by creating a
    temporary file. Falls back to static analysis if MATLAB is
    unavailable or fails.

    Parameters
    ----------
    command : str
        MATLAB command code to analyze
    environment : str
        Environment name to use for running MATLAB. Default is "_system".
    wdir : str, optional
        Working directory to create the temporary file in. Defaults to
        current directory.

    Returns
    -------
    dict
        Dictionary with 'inputs' and 'outputs' keys containing detected file paths.
    """
    if wdir is None:
        wdir = "."
    # Try MATLAB detection first by creating a temporary file
    temp_path = None
    try:
        # Create a temporary .m file to analyze dependencies
        with tempfile.NamedTemporaryFile(
            mode="w+t", suffix=".m", dir=wdir, delete=False
        ) as f:
            f.write(command)
            temp_path = f.name
        matlab_deps = get_deps_from_matlab(temp_path, environment)
        # Normalize dependency paths and remove the temporary file entry
        root_dir = os.path.realpath(wdir)
        temp_real = os.path.realpath(temp_path)
        temp_norm = Path(temp_real).as_posix()
        normalized_deps: list[str] = []
        for dep in matlab_deps:
            if not dep:
                continue
            # Resolve relative and absolute paths
            if os.path.isabs(dep):
                dep_full = os.path.realpath(dep)
            else:
                dep_full = os.path.realpath(os.path.join(root_dir, dep))
            # Filter out dependencies outside the working directory
            try:
                common = os.path.commonpath([root_dir, dep_full])
            except ValueError:
                # Different drives or invalid paths; treat as out-of-project
                continue
            if common != root_dir:
                continue
            dep_norm = Path(dep_full).as_posix()
            # Exclude the temporary file itself
            if dep_norm != temp_norm:
                # Convert to relative path from working directory
                dep_rel = os.path.relpath(dep_full, root_dir)
                normalized_deps.append(Path(dep_rel).as_posix())
        matlab_deps = normalized_deps
        # Use static analysis to detect data file I/O
        io_info = _detect_matlab_io_static(command, wdir, wdir=wdir)
        static_inputs = io_info["inputs"]
        outputs = io_info["outputs"]
        # Combine MATLAB dependencies with static inputs
        all_inputs = matlab_deps + static_inputs
        deps = list(dict.fromkeys(all_inputs))  # Remove duplicates
        return {"inputs": deps, "outputs": outputs}
    finally:
        # Clean up the temporary file
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                # File may have already been removed; ignore in cleanup
                pass
