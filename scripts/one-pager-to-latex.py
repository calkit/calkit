"""Convert the one-pager's Markdown into LaTeX for its PDF.

Each value marker becomes the value its results file holds now, linked to
the question on the project's hub whose evidence cites that file, and the
footer says what built it from where. No commit is named, since a file can't
name the commit it's committed in; that belongs to a release. The values are
written as calkit.sty's ``\\ckvalue``, which the template prints as is until
that package is used.
"""

from urllib.parse import urlparse

import pypandoc

import calkit
import calkit.markdown
import calkit.pipeline

DIR = "docs/one-pager"
SRC = f"{DIR}/main.md"
OUT = f"{DIR}/main.tex"


def escape_tex(text: str) -> str:
    for char, escaped in [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
    ]:
        text = text.replace(char, escaped)
    return text


ck_info = calkit.load_calkit_info()
hub = urlparse(ck_info.get("hub") or "https://calkit.io")
project = f"{hub.netloc or hub.path}/{ck_info['owner']}/{ck_info['name']}"
project_url = f"{hub.scheme or 'https'}://{project}"
with open(SRC, encoding="utf-8") as f:
    text = f.read()
# The values as the results files hold them now, then where each comes from
text, _ = calkit.markdown.set_values(text, SRC)
values = calkit.markdown.extract_values(text, SRC)
# A value links to the first question whose evidence cites its file
question_for_path: dict[str, int] = {}
for n, q in enumerate(ck_info.get("questions") or [], start=1):
    for ev in (q.get("evidence") or []) if isinstance(q, dict) else []:
        question_for_path.setdefault(ev.get("path"), n)
lines = text.splitlines(keepends=True)
for v in reversed(values):
    line = lines[v.line - 1]
    marker = calkit.markdown._VALUE_RE.search(line)
    assert marker is not None
    stage = calkit.pipeline.get_stage_for_output(v.path, ck_info) or ""
    tex = (
        rf"\ckvalue{{{escape_tex(v.key)}}}{{{escape_tex(v.text)}}}"
        rf"{{{escape_tex(v.path)}}}{{{escape_tex(stage)}}}"
    )
    number = question_for_path.get(v.path)
    if number is not None:
        tex = rf"\href{{{project_url}/questions/{number}}}{{{tex}}}"
    raw = "`" + tex + "`{=latex}"
    # Markers on a line are replaced last to first, so offsets hold
    lines[v.line - 1] = line[: marker.start()] + raw + line[marker.end() :]
text = "".join(lines)

version = calkit.__version__.split("+")[0]
footer = (
    rf"Built by Calkit v{version} from \href{{{project_url}}}{{{project}}}."
)
pypandoc.convert_text(
    text,
    "latex",
    format="markdown",
    outputfile=OUT,
    extra_args=[
        "--standalone",
        f"--template={DIR}/template.tex",
        f"--lua-filter={DIR}/one-pager.lua",
        "--shift-heading-level-by=-1",
        f"--variable=footer:{footer}",
    ],
)
