"""Core functionality for working with templates."""

from typing import Literal

from pydantic import BaseModel


class TemplateStringReplacement(BaseModel):
    path: str
    key: str


class Template(BaseModel):
    """Model for a template.

    Defines what kind of template it is, its name, and if/how we should allow
    for replacing strings in the template in the process of copying it to a
    project, e.g., if it's a LaTeX template and we want to automatically
    set the title.
    """

    kind: Literal["latex"]
    name: str
    loc: str | None = None  # Can be local (auto-detected by path) or URL
    filenames: list[str]  # Which filenames should be copied
    string_replacements: dict[str, list[str]] | None = None


# A registry of available templates, keyed by their kind and subkeyed by their
# name
# TODO: Maybe they should just be identified by name, since we may have
# some that don't fit the mold, e.g., JOSS
TEMPLATES = {
    "latex": {
        "article": Template(
            kind="latex",
            name="article",
            loc="templates/latex/article",
            filenames=["paper.tex"],
        ),
        "jfm": Template(
            kind="latex",
            name="jfm",
            loc="templates/latex/jfm",
            filenames=["paper.tex"],
        ),
    },
    "project": {},
}


def get_template(name: str) -> Template:
    """Get a template by name, which should include its namespace or type."""
    template_type, template_name = name.split("/")
    if template_name not in TEMPLATES:
        raise ValueError(f"Unknown template type '{template_type}'")
    templates = TEMPLATES[template_type]
    if template_name not in templates:
        raise ValueError(f"Unknown template name '{template_name}'")
    return templates[template_name]


def use_template(kind: Literal["latex"], name: str, dest_dir: str):
    """Copy template files into ``dest_dir``.

    The destination directory must be empty if it exists.

    TODO: Have generic .gitignore files as well.
    """
    pass
