"""IPython magics."""

import os
import pickle
import subprocess

from IPython.core import magic_arguments
from IPython.core.magic import Magics, cell_magic, magics_class

import calkit


@magics_class
class Calkit(Magics):

    @magic_arguments.magic_arguments()
    @magic_arguments.argument(
        "-n", "--name", help="Stage name.", required=True
    )
    @magic_arguments.argument(
        "--dep-var",
        "-d",
        help=(
            "Declare another stage's output variable as a dependency. "
            "Should be in the format '{stage_name}:{var_name}'. "
            "Optionally, the output format and engine, if applicable, can be "
            "appended like 'my-stage:some_dict:yaml' or "
            "'my-stage:df:parquet:pandas'."
        ),
        nargs="+",
    )
    @magic_arguments.argument(
        "--out-var",
        "-o",
        help=(
            "Declare a variable as an output. "
            "Optionally, the output format can be specified like "
            "'my_dict:json' or both the output format and engine can be "
            "specified like 'df:parquet:polars'."
        ),
        nargs="+",
    )
    @magic_arguments.argument(
        "--dep-path",
        "-D",
        help=(
            "Declare a path as a dependency, so that if that path changes, "
            "the stage will be rerun."
        ),
        nargs="+",
    )
    @magic_arguments.argument(
        "--out-path",
        "-O",
        help=(
            "Declare an output path written to by this cell, e.g., "
            "if a figure is saved to a file."
        ),
        nargs="+",
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
    )
    @magic_arguments.argument(
        "--out-param",
        "-p",
        help=(
            "Declare parameters or properties of the Calkit object like "
            "name=value."
        ),
        nargs="+",
    )
    @cell_magic
    def dvc_stage(self, line, cell):
        """Turn a notebook cell into a DVC pipeline stage.

        Note that all dependencies must be declared since the cell will be
        first turned into a script and then run as part of the DVC pipeline.

        Then variables will be loaded back into the user namespace state by
        loading the DVC output.
        """
        args = magic_arguments.parse_argstring(self.dvc_stage, line)
        # First, let's write this cell out to a script, ensuring that we
        # load the important state at the top
        script_txt = "# This script was automatically generated by Calkit\n\n"
        script_txt += "import calkit\n\n"
        if args.dep_var:
            for d in args.dep_var:
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
        if args.out_var:
            for out in args.out_var:
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
            "dvc",
            "stage",
            "add",
            "-q",
            "-n",
            args.name,
            "--run",
            "--force",
            "-d",
            script_fpath,
        ]
        if args.dep_var:
            for dep in args.dep_var:
                dep_split = dep.split(":")
                stage = dep_split[0]
                varname = dep_split[1]
                kws = dict(stage_name=stage, out_name=varname)
                if len(dep_split) > 2:
                    kws["fmt"] = dep_split[2]
                cmd += [
                    "-d",
                    calkit.get_notebook_stage_out_path(**kws),
                ]
        if args.dep_path:
            for dep in args.dep_path:
                cmd += ["-d", f"'{dep}'"]
        if args.out_var:
            for out in args.out_var:
                out_split = out.split(":")
                out_name = out_split[0]
                kws = dict(stage_name=args.name, out_name=out_name)
                if len(out_split) > 1:
                    kws["fmt"] = out_split[1]
                cmd += [
                    "-o",
                    calkit.get_notebook_stage_out_path(**kws),
                ]
        if args.out_path:
            for path in args.out_path:
                cmd += ["-o", f"{path}"]
        cmd.append(f"python '{script_fpath}'")
        try:
            subprocess.run(
                cmd, check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Error: {e.stderr}")
            raise e
        # Now let's read in and inject the outputs back into the IPython state
        if args.out_var:
            for out in args.out_var:
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


def load_ipython_extension(ipython):
    """Any module file that define a function named `load_ipython_extension`
    can be loaded via `%load_ext module.path` or be configured to be
    autoloaded by IPython at startup time.

    See https://ipython.readthedocs.io/en/stable/config/custommagics.html
    """
    # You can register the class itself without instantiating it
    # IPython will call the default constructor on it
    ipython.register_magics(Calkit)
