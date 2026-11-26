"""Tests for ``calkit.myst``."""

from pathlib import Path

import calkit.myst


def test_directives(tmp_path: Path) -> None:
    # Directives are found with colons or backticks, outside code, with a
    # path relative to the document, shown as its extension says unless
    # they say otherwise
    text = (
        ":::{ckprovenance} ../figures/plot.svg\n"
        ":label: fig-plot\n:width: 50%\nThe plot.\n:::\n"
        "```python\n:::{ckprovenance} in-code.png\n```\n"
        "```{ckprovenance} data.csv\n:rows: 2\n:::{ckprovenance} inside.png\n"
        "```\n"
        "::::{ckprovenance} notes.txt\n:kind: table\n:rows: many\n::::\n"
        ":::{figure} other.png\n:::\n"
        ":::{ckprovenance}\n:graph: false\n:::\n"
    )
    divs = calkit.myst.extract_directives(text, "site/pages/index.md")
    assert [(d.src, d.path, d.kind, d.line, d.rows) for d in divs] == [
        ("../figures/plot.svg", "site/figures/plot.svg", "figure", 1, 25),
        ("data.csv", "site/pages/data.csv", "table", 9, 2),
        ("notes.txt", "site/pages/notes.txt", "table", 13, 25),
        ("", "", "document", 19, 25),
    ]
    # Documents are found in the project's folder, but not what's built or
    # installed there
    (tmp_path / "site" / "pages").mkdir(parents=True)
    (tmp_path / "site" / "_build" / "site").mkdir(parents=True)
    (tmp_path / "site" / "node_modules").mkdir()
    for name in [
        "index.md",
        "pages/a.ipynb",
        "pages/b.md",
        "notes.txt",
        "_build/site/c.md",
        "node_modules/d.md",
    ]:
        (tmp_path / "site" / name).write_text("")
    assert calkit.myst.find_documents("site", wdir=str(tmp_path)) == [
        "site/index.md",
        "site/pages/a.ipynb",
        "site/pages/b.md",
    ]
    # The plugin has to be listed in myst.yml, which says how otherwise
    for config, ok in [
        (None, False),
        ("version: 1\nproject:\n  title: T\n", False),
        ("project:\n  plugins:\n    - other.mjs\n", False),
        ("project:\n  plugins:\n    - ./_extensions/calkit/myst.mjs\n", True),
        (
            "project:\n  plugins:\n    - type: javascript\n"
            "      path: _extensions/calkit/myst.mjs\n",
            True,
        ),
    ]:
        if config is not None:
            (tmp_path / "site" / "myst.yml").write_text(config)
        problem = calkit.myst.get_plugin_problem("site", wdir=str(tmp_path))
        assert (problem is None) == ok, config
        if problem is not None:
            assert calkit.myst.PLUGIN_CONFIG in problem
            assert "site/myst.yml" in problem
    calkit.myst.write_plugin("site", wdir=str(tmp_path))
    plugin_path = tmp_path / "site" / calkit.myst.PLUGIN_PATH
    assert plugin_path.read_text() == calkit.myst.PLUGIN_JS
    # The stage that builds it runs 'calkit myst build' in its folder
    ck_info = {
        "pipeline": {
            "stages": {
                "plot": {"kind": "python-script", "script_path": "p.py"},
                "other": {
                    "kind": "command",
                    "command": "calkit myst build -e _system",
                    "wdir": "elsewhere",
                },
                "site": {
                    "kind": "command",
                    "command": "calkit myst build -e _system -- --html",
                    "wdir": "site/",
                },
            }
        }
    }
    assert calkit.myst.get_build_stage("site", ck_info) == "site"
    assert calkit.myst.get_build_stage(".", ck_info) is None
