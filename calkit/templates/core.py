"""Core functionality for working with templates."""

from __future__ import annotations

import os
import shutil
from typing import Literal

from pydantic import BaseModel

from calkit.templates.latex import GITIGNORE as LATEX_GITIGNORE


class Template(BaseModel):
    """Model for a template.

    Defines what kind of template it is, its name, and if/how we should allow
    for replacing strings in the template in the process of copying it to a
    project, e.g., if it's a LaTeX template and we want to automatically
    set the title.

    Attributes
    ----------
    kind : string
        What kind of template is this.
    name : string
        Kebab-case name of the template.
    loc : string
        Location of the template. If not provided, will be inferred from the
        kind and name.
    files: list of strings
        Files to copy. If not specified, will copy all in the directory.
    gitignore : string
        Content to put into the ``.gitignore`` file.
    """

    kind: Literal["latex"]
    name: str
    loc: str | None = None  # Can be local (auto-detected by path) or URL
    files: list[str] | None = None  # Which filenames should be copied
    gitignore: str | None = None


class LatexTemplate(Template):
    kind: str = "latex"
    target: str = "paper.tex"
    gitignore: str = LATEX_GITIGNORE


# A registry of available templates, keyed by their kind and subkeyed by their
# name
TEMPLATES = {
    "latex": {
        "article": LatexTemplate(name="article"),
        "jfm": LatexTemplate(name="jfm"),
    },
    "project": {},
}


def get_template(name: str) -> Template:
    """Get a template by name, which should include its namespace or type."""
    template_type, template_name = name.split("/")
    if template_type not in TEMPLATES:
        raise ValueError(f"Unknown template type '{template_type}'")
    templates = TEMPLATES[template_type]
    if template_name not in templates:
        raise ValueError(f"Unknown template name '{template_name}'")
    return templates[template_name]


def use_template(name: str, dest_dir: str, **kwargs):
    """Copy template files into ``dest_dir``.

    The destination directory must be empty if it exists.
    """
    template = get_template(name)
    if template.loc is None:
        loc = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            template.kind,
            template.name,
        )
        print(loc)
    else:
        loc = template.loc
    if loc.startswith("http://") or loc.startswith("https://"):
        raise NotImplementedError("Remote template support not implemented")
    files = template.files
    if files is None:
        files = os.listdir(loc)
    if isinstance(template, LatexTemplate) and template.target not in files:
        files.append(template.target)
    if os.path.exists(dest_dir):
        if os.path.isfile(dest_dir):
            raise ValueError("Destination directory already exists as a file")
        if os.listdir(dest_dir):
            raise ValueError("Destination directory must be empty")
    else:
        os.makedirs(dest_dir)
    # Copy files into destination
    for fname in files:
        fpath = os.path.join(loc, fname)
        shutil.copy(src=fpath, dst=dest_dir)
    # Write gitignore if applicable
    if template.gitignore is not None:
        with open(os.path.join(dest_dir, ".gitignore"), "w") as f:
            f.write(template.gitignore)
    # If there's a title in kwargs and we're using a LaTeX template,
    # replace that line
    if isinstance(template, LatexTemplate) and "title" in kwargs:
        with open(os.path.join(dest_dir, template.target)) as f:
            lines = f.readlines()
        txt = ""
        for line in lines:
            if line.strip().startswith(r"\title{"):
                line = r"\title{" + kwargs["title"] + "}\n"
            txt += line
        with open(os.path.join(dest_dir, template.target), "w") as f:
            f.write(txt)
