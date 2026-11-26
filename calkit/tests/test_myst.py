"""Tests for ``calkit.myst``."""

import json
from pathlib import Path

import pytest

import calkit
import calkit.myst
from calkit.markdown import MarkdownParseError


def test_directives(tmp_path: Path) -> None:
    # Components are found with colons or backticks, outside code and
    # literal directives, whose closing fences don't open code blocks, named
    # by their directive, with a path relative to the project and options
    # as lines or a YAML block
    text = (
        ":::{ckfigure} figures/plot.svg\n"
        ":label: fig-plot\n:width: 50%\nThe plot.\n:::\n"
        "```python\n:::{ckfigure} in-code.png\n```\n"
        "```{note}\nA note.\n```\n"
        "```{cktable} data/clean.csv\n:name: tbl-data\n:rows: 2\n```\n"
        "```{code-cell} python\n:::{ckfigure} in-cell.png\n:::\n```\n"
        "~~~\n:::{ckfigure} in-tilde.png\n~~~\n"
        "::::{ckinclude} notes.md\n---\nprovenance: false\nrows: many\n---\n::::\n"
        ":::{figure} other.png\n:::\n"
        ":::{ckfigure}\n:::\n"
        "The slope is {ckvalue}`results/fit.json fit.slope .2f` and k is "
        "{ckvalue}`fit.ipynb k_25 provenance=false`, quoting "
        "{ckrefval}`liu2025 sigma`.\n"
        "```\n{ckvalue}`in-code.json x`\n```\n"
        ":::{include} part.md\n:::\n"
    )
    parts = {
        "site/pages/part.md": (
            ":::{cktable} inc.csv\n:::\n{ckvalue}`metrics n`\n"
            ":::{include} part.md\n:::\n:::{include} index.md\n:::\n"
        ),
        "site/pages/index.md": text,
    }
    components, roles = calkit.myst.extract_document(
        text,
        "site/pages/index.md",
        read_text=parts.get,
        results={"metrics": "results/metrics.yaml"},
    )
    assert [
        (c.kind, c.src, c.path, c.label, c.line, c.rows, c.provenance)
        for c in components
    ] == [
        (
            "figure",
            "figures/plot.svg",
            "figures/plot.svg",
            "fig-plot",
            1,
            25,
            True,
        ),
        ("table", "data/clean.csv", "data/clean.csv", "tbl-data", 12, 2, True),
        ("include", "notes.md", "notes.md", "", 23, 25, False),
        # Included, once, however files include each other
        ("table", "inc.csv", "inc.csv", "", 1, 25, True),
    ]
    # Values from roles read as Quarto's shortcodes do, with their role and
    # content, as the plugin finds them, from what's included too
    assert [
        (name, args, v.path, v.key, v.format, v.ref, v.provenance, v.line)
        for name, args, v in roles
    ] == [
        (
            "ckvalue",
            "results/fit.json fit.slope .2f",
            "results/fit.json",
            "fit.slope",
            ".2f",
            None,
            True,
            33,
        ),
        (
            "ckvalue",
            "fit.ipynb k_25 provenance=false",
            ".calkit/notebooks/outputs/fit.ipynb/values.json",
            "k_25",
            None,
            None,
            False,
            33,
        ),
        (
            "ckrefval",
            "liu2025 sigma",
            ".calkit/reference-values/liu2025.json",
            "sigma",
            None,
            ("liu2025", "sigma"),
            True,
            33,
        ),
        (
            "ckvalue",
            "metrics n",
            "results/metrics.yaml",
            "n",
            None,
            None,
            True,
            3,
        ),
    ]
    # A mistake in one names its line
    with pytest.raises(MarkdownParseError, match="names no key") as e:
        calkit.myst.extract_document("\n{ckvalue}`a.json`\n", "site/index.md")
    assert e.value.line == 2
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
    # What roles show is added to the record by their role and content
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps({"values": {}}))
    calkit.myst.add_role_values(str(record_path), roles[:2], ["0.12", "0.031"])
    assert json.loads(record_path.read_text())["roles"] == {
        "ckvalue": {
            "results/fit.json fit.slope .2f": {
                "text": "0.12",
                "key": "results/fit.json:fit.slope",
                "provenance": True,
            },
            "fit.ipynb k_25 provenance=false": {
                "text": "0.031",
                "key": ".calkit/notebooks/outputs/fit.ipynb/values.json:k_25",
                "provenance": False,
            },
        }
    }
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
    # What it shows has to be among its inputs, or in one, unless it makes
    # it, for it to rebuild when that changes
    paths = ["figures/plot.svg", "data/a.csv", "site/_build/x.png", "b.csv"]
    assert calkit.myst.get_unlisted_paths(paths, "site", str(tmp_path)) == []
    with open(tmp_path / "dvc.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "stages": {
                    "site": {
                        "wdir": "site",
                        "deps": ["index.md", "../figures/plot.svg", "../data"],
                        "outs": [{"_build": {"cache": False}}],
                    }
                }
            },
            f,
        )
    # And exists or another stage makes it, since otherwise it can't be
    (tmp_path / "b.csv").write_text("")
    assert calkit.myst.get_unlisted_paths(
        paths + ["b.csv", "gone.csv"], "site", str(tmp_path)
    ) == ["b.csv"]
    assert calkit.myst.get_unlisted_paths(paths, "other", str(tmp_path)) == []
