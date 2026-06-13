/**
 * Self-contained I/O tracking code that can be injected into notebook kernels.
 * No dependencies required - works in any environment.
 */

/**
 * Python code to inject when starting I/O tracking.
 * Monkey-patches open() and pathlib.Path.open() to track file operations.
 */
export const PYTHON_START_TRACKING = `
import os as _calkit_os
from pathlib import Path as _calkit_Path

_calkit_project_root = _calkit_os.getcwd()
_calkit_inputs = set()
_calkit_outputs = set()
_calkit_tracking = False
_calkit_original_open = open
_calkit_original_path_open = _calkit_Path.open

def _calkit_should_track(path):
    abs_path = _calkit_os.path.abspath(str(path))
    if not abs_path.startswith(_calkit_project_root):
        return False
    ignore = ['.ipynb_checkpoints', '__pycache__', '.git/', '.dvc/',
              '.calkit/', 'site-packages/', 'dist-packages/', '/tmp/',
              '.pyc', '.ipynb']
    return not any(p in abs_path for p in ignore)

def _calkit_tracked_open(file, mode='r', *args, **kwargs):
    f = _calkit_original_open(file, mode, *args, **kwargs)
    if _calkit_tracking and isinstance(file, (str, bytes)) or hasattr(file, '__fspath__'):
        path = _calkit_os.fspath(file) if hasattr(file, '__fspath__') else str(file)
        if _calkit_should_track(path):
            rel = _calkit_os.path.relpath(path, _calkit_project_root)
            if 'r' in mode and not any(m in mode for m in ['w', 'a', '+']):
                _calkit_inputs.add(rel)
            elif any(m in mode for m in ['w', 'a', 'x', '+']):
                _calkit_outputs.add(rel)
    return f

def _calkit_tracked_path_open(self, mode='r', *args, **kwargs):
    f = _calkit_original_path_open(self, mode, *args, **kwargs)
    if _calkit_tracking and _calkit_should_track(str(self)):
        rel = _calkit_os.path.relpath(str(self), _calkit_project_root)
        if 'r' in mode and not any(m in mode for m in ['w', 'a', '+']):
            _calkit_inputs.add(rel)
        elif any(m in mode for m in ['w', 'a', 'x', '+']):
            _calkit_outputs.add(rel)
    return f

__builtins__['open'] = _calkit_tracked_open
_calkit_Path.open = _calkit_tracked_path_open
_calkit_tracking = True
`.trim();

/**
 * Python code to retrieve detected files.
 * Returns a dict with 'inputs' and 'outputs' lists.
 */
export const PYTHON_GET_DETECTED = `
{'inputs': sorted(list(_calkit_inputs)), 'outputs': sorted(list(_calkit_outputs))}
`.trim();

/**
 * Python code to stop tracking and restore original functions.
 */
export const PYTHON_STOP_TRACKING = `
_calkit_tracking = False
__builtins__['open'] = _calkit_original_open
_calkit_Path.open = _calkit_original_path_open
`.trim();

/**
 * R code to start tracking I/O operations.
 * Overrides file() and other I/O functions.
 */
export const R_START_TRACKING = `
.calkit_inputs <- character(0)
.calkit_outputs <- character(0)
.calkit_tracking <- TRUE
.calkit_project_root <- getwd()
.calkit_original_file <- file

.calkit_should_track <- function(path) {
  abs_path <- normalizePath(path, mustWork = FALSE)
  if (!startsWith(abs_path, .calkit_project_root)) return(FALSE)
  ignore <- c(".ipynb_checkpoints", ".git/", ".dvc/", ".calkit/", "/tmp/")
  !any(sapply(ignore, function(p) grepl(p, abs_path, fixed = TRUE)))
}

file <- function(description = "", open = "", ...) {
  conn <- .calkit_original_file(description, open, ...)
  if (.calkit_tracking && is.character(description) && .calkit_should_track(description)) {
    rel_path <- sub(paste0("^", .calkit_project_root, "/"), "", normalizePath(description, mustWork = FALSE))
    if (grepl("r", open) && !grepl("[wa+]", open)) {
      .calkit_inputs <<- unique(c(.calkit_inputs, rel_path))
    } else if (grepl("[wa]", open)) {
      .calkit_outputs <<- unique(c(.calkit_outputs, rel_path))
    }
  }
  conn
}
`.trim();

/**
 * R code to retrieve detected files.
 */
export const R_GET_DETECTED = `
list(inputs = .calkit_inputs, outputs = .calkit_outputs)
`.trim();

/**
 * Julia code to start tracking I/O operations.
 */
export const JULIA_START_TRACKING = `
const _calkit_inputs = Set{String}()
const _calkit_outputs = Set{String}()
_calkit_tracking = Ref(true)
const _calkit_project_root = pwd()
const _calkit_original_open = Base.open

function _calkit_should_track(path::AbstractString)
    abs_path = abspath(path)
    !startswith(abs_path, _calkit_project_root) && return false
    ignore = [".ipynb_checkpoints", ".git/", ".dvc/", ".calkit/", "/tmp/"]
    !any(p -> occursin(p, abs_path), ignore)
end

function Base.open(f::AbstractString, mode::AbstractString="r"; kwargs...)
    io = _calkit_original_open(f, mode; kwargs...)
    if _calkit_tracking[] && _calkit_should_track(f)
        rel_path = relpath(f, _calkit_project_root)
        if occursin("r", mode) && !occursin(r"[wa+]", mode)
            push!(_calkit_inputs, rel_path)
        elseif occursin(r"[wa]", mode)
            push!(_calkit_outputs, rel_path)
        end
    end
    io
end
`.trim();

/**
 * Julia code to retrieve detected files.
 */
export const JULIA_GET_DETECTED = `
Dict("inputs" => sort(collect(_calkit_inputs)), "outputs" => sort(collect(_calkit_outputs)))
`.trim();

/**
 * Get tracking code for a specific kernel language.
 */
export function getTrackingCode(language: string): {
  start: string;
  get: string;
  stop?: string;
} | null {
  const lang = language.toLowerCase();

  if (lang === "python" || lang === "python3") {
    return {
      start: PYTHON_START_TRACKING,
      get: PYTHON_GET_DETECTED,
      stop: PYTHON_STOP_TRACKING,
    };
  }

  if (lang === "r" || lang === "ir") {
    return {
      start: R_START_TRACKING,
      get: R_GET_DETECTED,
    };
  }

  if (lang === "julia") {
    return {
      start: JULIA_START_TRACKING,
      get: JULIA_GET_DETECTED,
    };
  }

  return null;
}

/**
 * Parse detected files from kernel execution result.
 * Handles different output formats from different kernels.
 */
export function parseDetectedFiles(
  result: any,
): { inputs: string[]; outputs: string[] } | null {
  try {
    // Python returns a dict literal as text/plain
    if (result?.content?.data?.["text/plain"]) {
      const text = result.content.data["text/plain"];
      // Parse Python dict or eval safely
      const parsed = eval(`(${text})`);
      return {
        inputs: parsed.inputs || [],
        outputs: parsed.outputs || [],
      };
    }

    // R and Julia might return JSON
    if (result?.content?.data?.["application/json"]) {
      const data = result.content.data["application/json"];
      return {
        inputs: data.inputs || [],
        outputs: data.outputs || [],
      };
    }
  } catch (error) {
    console.error("Failed to parse detected files:", error);
  }

  return null;
}
