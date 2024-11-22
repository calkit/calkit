"""IPython magics."""

from IPython.core import magic_arguments
from IPython.core.magic import (
    Magics,
    cell_magic,
    magics_class,
)


@magics_class
class Calkit(Magics):

    @magic_arguments.magic_arguments()
    @magic_arguments.argument("-n", "--name", help="Stage name.", required=True)
    @magic_arguments.argument("--dep", help="Declare a dependency.", nargs="+")
    @magic_arguments.argument("--out", help="Declare an output.", nargs="+")
    @cell_magic
    def dvc_stage(self, line, cell):
        args = magic_arguments.parse_argstring(self.dvc_stage, line)
        self.shell.run_cell(cell)
        for out in args.out:
            if out in self.shell.user_ns:
                print("Found", out)


def load_ipython_extension(ipython):
    """Any module file that define a function named `load_ipython_extension`
    can be loaded via `%load_ext module.path` or be configured to be
    autoloaded by IPython at startup time.

    See https://ipython.readthedocs.io/en/stable/config/custommagics.html
    """
    # You can register the class itself without instantiating it
    # IPython will call the default constructor on it
    ipython.register_magics(Calkit)
