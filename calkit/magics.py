"""IPython magics."""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

from IPython.core import magic_arguments
from IPython.core.magic import Magics, cell_magic, magics_class

import calkit


def _parse_string_arg(val: str):
    try:
        return ast.literal_eval(val)
    except (ValueError, SyntaxError):
        return val
    return val


def _posix_path(path: str):
    return pathlib.Path(path).as_posix()


@magics_class
class Calkit(Magics):
    @magic_arguments.magic_arguments()
    @magic_arguments.argument(
        "-n",
        "--name",
        help="Stage name.",
        required=True,
        type=_parse_string_arg,
    )
    @magic_arguments.argument(
        "--env",
        nargs="?",
        const=True,
        help=(
            "Whether or not this cell should be run in an environment. "
            "If no environment name is provided, the default will be used."
        ),
    )
    @magic_arguments.argument(
        "--dep",
        "-d",
        help=(
            "Declare another stage's output variable as a dependency. "
            "Should be in the format '{stage_name}:{var_name}'. "
            "Optionally, the output format and engine, if applicable, can be "
            "appended like 'my-stage:some_dict:yaml' or "
            "'my-stage:df:parquet:pandas'."
        ),
        nargs="+",
        type=_parse_string_arg,
    )
    @magic_arguments.argument(
        "--out",
        "-o",
        help=(
            "Declare a variable as an output. "
            "Optionally, the output format can be specified like "
            "'my_dict:json' or both the output format and engine can be "
            "specified like 'df:parquet:polars'."
        ),
        nargs="+",
        type=_parse_string_arg,
    )
    @magic_arguments.argument(
        "--dep-path",
        "-D",
        help=(
            "Declare a path as a dependency, so that if that path changes, "
            "the stage will be rerun."
        ),
        nargs="+",
        type=_parse_string_arg,
    )
    @magic_arguments.argument(
        "--out-path",
        "-O",
        help=(
            "Declare an output path written to by this cell, e.g., "
            "if a figure is saved to a file."
        ),
        nargs="+",
        type=_parse_string_arg,
    )
    @magic_arguments.argument(
        "--out-type",
        "-t",
        choices=["figure", "dataset"],
        help=(
            "Declare the output as a type of Calkit object. If --out-path "
            "is specified, that will be used as the object path, else its "
            "path will be set as the output variable path. "
            "Note that there must only be one output to use this option."
        ),
        type=_parse_string_arg,
    )
    @magic_arguments.argument(
        "--out-title",
        help="Title for Calkit output object.",
        type=_parse_string_arg,
    )
    @magic_arguments.argument(
        "--out-desc",
        help="Description for Calkit output object.",
        type=_parse_string_arg,
    )
    @cell_magic
    def stage(self, line, cell):
        """Turn a notebook cell into a DVC pipeline stage.

        Note that all dependencies must be declared since the cell will be
        first turned into a script and then run as part of the DVC pipeline.

        Then variables will be loaded back into the user namespace state by
        loading the DVC output.
        """
        # Allow command for this line to continue with backslashes
        cell_split = cell.split("\n")
        line_combined = line.strip().removesuffix("\\")
        while line.strip().endswith("\\"):
            newline = cell_split.pop(0)
            line += newline
            line_combined += " " + newline.strip().removesuffix("\\")
        cell = "\n".join(cell_split)
        args = magic_arguments.parse_argstring(self.stage, line_combined)
        # If an output object type is specified, make sure we only have one
        # output
        if args.out_type:
            all_outs = []
            if args.out:
                all_outs += args.out
            if args.out_path:
                all_outs = args.out_path
            if len(all_outs) != 1:
                raise ValueError(
                    "Only one output can be defined if declaring as a "
                    "Calkit object"
                )
            # Parse calkit object parameters
            out_params = {}
            if args.out_title:
                out_params["title"] = args.out_title
            if args.out_desc:
                out_params["description"] = args.out_desc
            # Ensure we have required keys
            # TODO: Use Pydantic here
            if "title" not in out_params:
                raise ValueError(
                    f"Calkit type {args.out_type} requires a title"
                )
            # Parse output path
            if args.out_path:
                out_params["path"] = args.out_path[0]
            elif args.out:
                out = args.out[0]
                out_split = out.split(":")
                kws = dict(stage_name=args.name, out_name=out_split[0])
                if len(out_split) > 1:
                    kws["fmt"] = out_split[1]
                out_path = calkit.get_notebook_stage_out_path(**kws)
                out_params["path"] = out_path
            out_params["stage"] = args.name
            # Save in calkit.yaml
            ck_info = calkit.load_calkit_info()
            objs = ck_info.get(args.out_type + "s", [])
            objs = [obj for obj in objs if obj["path"] != out_params["path"]]
            objs.append(out_params)
            ck_info[args.out_type + "s"] = objs
            with open("calkit.yaml", "w") as f:
                calkit.ryaml.dump(ck_info, f)
        # First, let's write this cell out to a script, ensuring that we
        # load the important state at the top
        script_txt = "# This script was automatically generated by Calkit\n\n"
        script_txt += "import calkit\n\n"
        if args.dep:
            for d in args.dep:
                dep_split = d.split(":")
                stage = dep_split[0]
                varname = dep_split[1]
                fmt_string = ""
                eng_string = ""
                if len(dep_split) >= 3:
                    fmt_string = f", fmt='{dep_split[2]}'"
                if len(dep_split) == 4:
                    eng_string = f", engine='{dep_split[3]}'"
                script_txt += (
                    f"{varname} = calkit.load_notebook_stage_out("
                    f"stage_name='{stage}', out_name='{varname}'"
                    f"{fmt_string}{eng_string})\n\n"
                )
        script_txt += cell
        # Add lines that save our output variables to files
        if args.out:
            for out in args.out:
                fmt_string = ""
                eng_string = ""
                out_split = out.split(":")
                outvar = out_split[0]
                if len(out_split) > 1:
                    fmt_string = f", fmt='{out_split[1]}'"
                if len(out_split) == 3:
                    eng_string = f", engine='{out_split[2]}'"
                script_txt += (
                    f"calkit.save_notebook_stage_out("
                    f"{outvar}, stage_name='{args.name}', out_name='{outvar}'"
                    f"{fmt_string}{eng_string})\n"
                )
        # Save the script to a Python file
        script_fpath = calkit.get_notebook_stage_script_path(args.name)
        script_dir = os.path.dirname(script_fpath)
        os.makedirs(script_dir, exist_ok=True)
        outs_dir = calkit.get_notebook_stage_out_dir(stage_name=args.name)
        os.makedirs(outs_dir, exist_ok=True)
        with open(script_fpath, "w") as f:
            f.write(script_txt)
        # Create a DVC stage that runs the script, defining the appropriate
        # dependencies and outputs, and run it
        cmd = [
            sys.executable,
            "-m",
            "dvc",
            "stage",
            "add",
            "-q",
            "-n",
            args.name,
            "--run",
            "--force",
            "-d",
            _posix_path(script_fpath),
        ]
        if args.dep:
            for dep in args.dep:
                dep_split = dep.split(":")
                stage = dep_split[0]
                varname = dep_split[1]
                kws = dict(stage_name=stage, out_name=varname)
                if len(dep_split) > 2:
                    kws["fmt"] = dep_split[2]
                cmd += [
                    "-d",
                    _posix_path(calkit.get_notebook_stage_out_path(**kws)),
                ]
        if args.dep_path:
            for dep in args.dep_path:
                cmd += ["-d", _posix_path(dep)]
        if args.out:
            for out in args.out:
                out_split = out.split(":")
                out_name = out_split[0]
                kws = dict(stage_name=args.name, out_name=out_name)
                if len(out_split) > 1:
                    kws["fmt"] = out_split[1]
                cmd += [
                    "-o",
                    _posix_path(calkit.get_notebook_stage_out_path(**kws)),
                ]
        if args.out_path:
            for path in args.out_path:
                cmd += ["-o", _posix_path(path)]
        stage_cmd = f'python "{_posix_path(script_fpath)}"'
        if args.env:
            xenv = "calkit xenv"
            if isinstance(args.env, str):
                xenv += f" -n {args.env}"
            stage_cmd = xenv + " -- " + stage_cmd
        cmd.append(stage_cmd)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"Error: {e.stderr}")
            raise e
        # Now let's read in and inject the outputs back into the IPython state
        if args.out:
            for out in args.out:
                out_split = out.split(":")
                out_name = out_split[0]
                kws = dict(stage_name=args.name, out_name=out_name)
                if len(out_split) > 1:
                    kws["fmt"] = out_split[1]
                if len(out_split) > 2:
                    kws["engine"] = out_split[2]
                self.shell.user_ns[out_name] = calkit.load_notebook_stage_out(
                    **kws
                )
        # If the last line of the cell has no equals signs, run that command,
        # since it's probably meant for display
        last_line = cell.strip().split("\n")[-1]
        if "=" not in last_line:
            self.shell.run_cell(last_line)


def load_ipython_extension(ipython):
    """Any module file that define a function named `load_ipython_extension`
    can be loaded via `%load_ext module.path` or be configured to be
    autoloaded by IPython at startup time.

    See https://ipython.readthedocs.io/en/stable/config/custommagics.html
    """
    # You can register the class itself without instantiating it
    # IPython will call the default constructor on it
    ipython.register_magics(Calkit)
