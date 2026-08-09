"""Models related to projects."""

from pydantic import BaseModel

from app.models import Figure, Notebook, Publication


class ShowcaseFigureInput(BaseModel):
    figure: str


class ShowcasePublicationInput(BaseModel):
    publication: str


class ShowcaseFigure(BaseModel):
    figure: Figure


class ShowcasePublication(BaseModel):
    publication: Publication


class ShowcaseText(BaseModel):
    text: str


class ShowcaseMarkdown(BaseModel):
    markdown: str


class ShowcaseMarkdownFileInput(BaseModel):
    markdown_file: str


class ShowcaseYamlFileInput(BaseModel):
    yaml_file: str
    object_name: str | None = None


class ShowcaseYaml(BaseModel):
    yaml: str


class ShowcaseNotebookInput(BaseModel):
    notebook: str


class ShowcaseNotebook(BaseModel):
    notebook: Notebook


class ShowcaseInput(BaseModel):
    elements: list[
        ShowcaseFigureInput
        | ShowcasePublicationInput
        | ShowcaseText
        | ShowcaseMarkdownFileInput
        | ShowcaseMarkdown
        | ShowcaseYamlFileInput
        | ShowcaseNotebookInput
    ]


class Showcase(BaseModel):
    elements: list[
        ShowcaseFigure
        | ShowcasePublication
        | ShowcaseText
        | ShowcaseMarkdown
        | ShowcaseYaml
        | ShowcaseNotebook
    ]
