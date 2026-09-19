"""Core functionality for working with templates."""

from __future__ import annotations

import os
import shutil
from typing import Literal

from pydantic import BaseModel, model_validator

from calkit.templates.latex import GITIGNORE as LATEX_GITIGNORE

# The hub a template lives on when it isn't shipped inside this package.
# A project template is a real project someone can open, fork, and read,
# which is a thing a hub has and a Python package doesn't.
CALKIT_HUB_URL = "https://calkit.io"


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
    title : string
        Human-readable name, for picking the template from a list.
    description : string
        What the template is for, a sentence at most.
    """

    kind: str
    name: str
    loc: str | None = None  # Can be local (auto-detected by path) or URL
    files: list[str] | None = None  # Which filenames should be copied
    gitignore: str | None = None
    title: str | None = None
    description: str | None = None

    @property
    def ref(self) -> str:
        """How a caller asks for this template by name.

        Namespaced, since names only have to be unique within a kind.
        """
        return f"{self.kind}/{self.name}"


class LatexTemplate(Template):
    kind: Literal["latex"] = "latex"
    target: str = "paper.tex"
    gitignore: str = LATEX_GITIGNORE


class ProjectTemplate(Template):
    """A whole project to start from.

    Unlike a LaTeX template, which is a handful of files shipped in this
    package, a project template is a project on a hub: it has a pipeline
    that runs, outputs in storage, and a history. It is identified by where
    it lives, so a different hub can offer its own.
    """

    kind: Literal["project"] = "project"
    owner: str = "calkit"
    hub_url: str = CALKIT_HUB_URL
    # Where the repo itself is, so starting from a known template doesn't
    # need a hub to be reachable, or logged into, to find out.
    git_repo_url: str = ""

    @model_validator(mode="after")
    def set_locations(self) -> ProjectTemplate:
        if self.loc is None:
            self.loc = f"{self.hub_url}/{self.owner}/{self.name}"
        if not self.git_repo_url:
            self.git_repo_url = f"https://github.com/{self.owner}/{self.name}"
        return self

    @property
    def ref(self) -> str:
        """``owner/name``, which is how a hub names one of its projects."""
        return f"{self.owner}/{self.name}"


# A registry of available templates, keyed by their kind and subkeyed by their
# name
TEMPLATES: dict[str, dict[str, Template]] = {
    "latex": {
        "article": LatexTemplate(
            name="article",
            title="Article (generic)",
            description="A plain article, for a journal without its own class.",
        ),
        "ieee-conference": LatexTemplate(
            name="ieee-conference",
            title="IEEE conference paper",
            description="Two-column paper in the IEEEtran conference format.",
        ),
        "jfm": LatexTemplate(
            name="jfm",
            title="Journal of Fluid Mechanics",
            description="Article in the JFM class.",
        ),
        "report": LatexTemplate(
            name="report",
            title="Report or thesis (chapters)",
            description="A longer document organized into chapters.",
        ),
    },
    # Ordered as they should be offered: the one most people want first.
    # TODO: rewrite these titles and descriptions
    "project": {
        "example-basic": ProjectTemplate(
            name="example-basic",
            title="Basic",
            description="uv environment, Python analysis, LaTeX paper.",
        ),
        "example-analytics": ProjectTemplate(
            name="example-analytics",
            title="Analytics",
            description="Notebook analysis, figures and tables.",
        ),
        "example-r": ProjectTemplate(
            name="example-r",
            title="R",
            description="renv environment, R analysis, figures.",
        ),
        "example-julia": ProjectTemplate(
            name="example-julia",
            title="Julia",
            description="Julia environment, script and notebook, LaTeX paper.",
        ),
        "example-matlab": ProjectTemplate(
            name="example-matlab",
            title="MATLAB",
            description="Scripts run in batch mode.",
        ),
    },
}


def get_template(name: str) -> Template:
    """Get a template by its ref, e.g. 'latex/article', 'calkit/example-r'.

    Refs are namespaced, but not all by kind: a project template is named
    by its owner on a hub. Matching the whole ref covers both.
    """
    template = find_template(name)
    if template is not None:
        return template
    template_type, _, template_name = name.partition("/")
    if template_type in TEMPLATES:
        raise ValueError(f"Unknown template name '{template_name}'")
    raise ValueError(f"Unknown template '{name}'")


def find_template(ref: str, kind: str | None = None) -> Template | None:
    """The known template *ref* names, or None if nothing is registered.

    Matched on ``ref`` rather than ``name``, so 'latex/article' and
    'calkit/example-r' each find the one they mean.
    """
    for template in get_templates(kind=kind):
        if template.ref == ref:
            return template
    return None


def get_templates(kind: str | None = None) -> list[Template]:
    """Every known template, or only those of one kind.

    In the order they should be offered, since the registry is written in
    that order and nothing downstream knows better.
    """
    if kind is not None:
        if kind not in TEMPLATES:
            raise ValueError(f"Unknown template kind '{kind}'")
        kinds = [kind]
    else:
        kinds = list(TEMPLATES)
    return [template for k in kinds for template in TEMPLATES[k].values()]


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
    else:
        loc = template.loc
    if loc.startswith("http://") or loc.startswith("https://"):
        # A project template is a project on a hub, so starting from one is
        # the hub's job (it forks the repo and copies the outputs); there
        # are no files here to copy.
        raise NotImplementedError(
            f"Template '{name}' lives at {loc} and can't be copied from here"
        )
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
