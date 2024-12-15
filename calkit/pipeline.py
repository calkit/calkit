"""Functionality for building DVC pipelines with Python."""

import inspect
from typing import Callable

from pydantic import BaseModel


class Dependency(BaseModel):
    path: str


class Output(BaseModel):
    path: str


class Figure(Output):
    title: str
    description: str | None = None


class Dataset(Output):
    title: str
    description: str | None = None


def _get_func_src_no_decorator(func: Callable) -> str:
    func_src = inspect.getsource(func)
    func_src_split = func_src.split("\n")
    func_src = ""
    started = False
    for line in func_src_split:
        if line.startswith("def "):
            started = True
        if started:
            func_src += line + "\n"
    return func_src


def _func_to_script(func: Callable) -> str:
    """Create module source code to produce a standalone function."""
    txt = ""
    func_src = _get_func_src_no_decorator(func)
    module = inspect.getmodule(func)
    module_src = inspect.getsource(module)
    global_deps = inspect.getclosurevars(func).globals
    for name, obj in global_deps.items():
        if inspect.isfunction(obj):
            # TODO: What if this function has global deps?
            txt += "\n\n" + inspect.getsource(obj) + "\n\n"
        elif inspect.ismodule(obj):
            txt += f"\n\nimport {obj.__name__} as {name}\n\n"
        else:
            # TODO: This needs to be more robust
            # Maybe we should take all of the module source
            for line in module_src.split("\n"):
                if line.replace(" ", "").startswith(f"{name}="):
                    txt += "\n\n" + line + "\n\n"
    txt += "\n\n" + func_src + "\n"
    # Call the function at the end of the script
    txt += f"\n\n{func.__name__}()\n"
    return txt


class Pipeline(BaseModel):
    deps: list[Dependency] | None = None

    def stage(self, *args, other_arg=None):
        """A decorator that creates a pipeline stage."""

        def decorator(func: Callable):

            print("Stage being created from", func)
            print("Other arg:", other_arg)
            func_src = inspect.getsource(func)
            print("Global deps:", inspect.getclosurevars(func).globals)

            module = inspect.getmodule(func)
            print("Module:", module)
            module_src = inspect.getsource(module)
            module_members = inspect.getmembers(module)
            imports = inspect.getmembers(module, inspect.ismodule)
            print("Module members:", module_members)
            print("Imports:", imports)

            # Write source code to file
            # Detect any imports, helper functions, or module-level variables
            # Remove decorator line(s) by trimming off all before the "def "
            func_src_split = func_src.split("\n")
            func_src = ""
            started = False
            for line in func_src_split:
                if line.startswith("def "):
                    started = True
                if started:
                    func_src += line + "\n"

            print("Func source:", func_src)

            script_src = _func_to_script(func)

            print("Script source:", script_src)

            # Create DVC stage from function name

            # Run the DVC stage and load/return the output

            def wrapper(*args, **kwargs):
                print(f"Calling {func.__name__} with instance {self}...")
                result = func(*args, **kwargs)
                print(f"{func.__name__} finished. Result: {result}")
                return result

            return wrapper

        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])

        return decorator

    def run(self):
        """Run the pipeline."""
        print("Running")
        pass
