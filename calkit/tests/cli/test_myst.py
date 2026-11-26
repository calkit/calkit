"""Tests for ``calkit.cli.myst``."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import calkit
import calkit.myst
import calkit.quarto


@pytest.mark.skipif(shutil.which("myst") is None, reason="needs MyST")
def test_build(tmp_path: Path) -> None:
    import nbformat

    def build(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "myst", "build", *args],
            capture_output=True,
            text=True,
            cwd=tmp_path / "site",
        )

    def read_export() -> str:
        with open(tmp_path / "site" / "_build" / "exports" / "index.md") as f:
            return f.read().replace("\xa0", " ")

    def get_summaries(text: str) -> list[str]:
        return re.findall(r"^:{3,}\{dropdown\} (.*)$", text, re.M)

    subprocess.check_call(["calkit", "init"], cwd=tmp_path)
    subprocess.check_call(
        ["git", "remote", "add", "origin", "git@github.com:example/proj.git"],
        cwd=tmp_path,
    )
    for folder in ["scripts", "data", "figures", "results", "site"]:
        (tmp_path / folder).mkdir()
    (tmp_path / "data" / "raw.csv").write_text("x,y\n1,2\n3,4\n")
    (tmp_path / "scripts" / "clean.py").write_text(
        "import json, shutil\n"
        "shutil.copy('data/raw.csv', 'data/clean.csv')\n"
        "json.dump({'fit': {'slope': 0.123456}}, "
        "open('results/fit.json', 'w'))\n"
    )
    (tmp_path / "scripts" / "plot.py").write_text(
        "open('figures/plot.svg', 'w').write(\n"
        '    \'<svg xmlns="http://www.w3.org/2000/svg" width="10" '
        'height="10"/>\'\n)\n'
    )
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell("k_25 = 0.0309")]
    nbformat.write(nb, str(tmp_path / "fit.ipynb"))
    subprocess.check_call(
        ["calkit", "new", "uv-venv", "-n", "py", "ipykernel"], cwd=tmp_path
    )
    stage = {"kind": "python-script", "environment": "_system"}
    ck_info: dict = calkit.load_calkit_info(wdir=str(tmp_path))
    ck_info.update(
        {
            "requirements": ["myst"],
            "datasets": [
                {"path": "data/raw.csv", "created_by": {"name": "Jo"}}
            ],
            "references": [
                {
                    "path": "refs.bib",
                    "values": {
                        "liu2025": {"sigma": {"value": 0.1, "page": 4}}
                    },
                }
            ],
        }
    )
    site_inputs = [
        "index.md",
        "myst.yml",
        "../figures/plot.svg",
        "../data/clean.csv",
        "../.calkit/notebooks/outputs/fit.ipynb/values.json",
        "../results/fit.json",
    ]
    ck_info["pipeline"] = {
        "stages": {
            "clean": {
                **stage,
                "script_path": "scripts/clean.py",
                "inputs": ["data/raw.csv"],
                "outputs": [
                    {"path": "data/clean.csv", "storage": "git"},
                    {"path": "results/fit.json", "storage": "git"},
                ],
            },
            "plot": {
                **stage,
                "script_path": "scripts/plot.py",
                "inputs": ["data/clean.csv"],
                "outputs": [{"path": "figures/plot.svg", "storage": "git"}],
            },
            "fit": {
                "kind": "jupyter-notebook",
                "notebook_path": "fit.ipynb",
                "environment": "py",
                "html_storage": None,
                "cell_outputs": [
                    {
                        "kind": "value",
                        "cell_id": nb.cells[0].id,
                        "variable_name": "k_25",
                    }
                ],
            },
            "site": {
                "kind": "command",
                "wdir": "site",
                "command": "calkit myst build -e _system -- index.md --md --ci",
                "environment": "_system",
                # Without one of what it shows, at first
                "inputs": site_inputs[:-1],
                "outputs": ["_build/exports"],
            },
        }
    }
    with open(tmp_path / "calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    (tmp_path / "refs.bib").write_text(
        "@article{liu2025, title={T}, author={Liu}, year={2025}}\n"
    )
    # With a directive in backticks first, whose closing fence doesn't open
    # a code block
    (tmp_path / "site" / "index.md").write_text(
        "# Report\n\n```{tip}\nA tip.\n```\n\n"
        ":::{ckfigure} figures/plot.svg\n:label: fig-plot\n"
        "The plot.\n:::\n\n"
        "The slope is {ckvalue}`results/fit.json fit.slope .3f`, k is "
        "{ckvalue}`fit.ipynb k_25 .3f`, sigma is {ckrefval}`liu2025 sigma`, "
        "and not shown, "
        "{ckvalue}`results/fit.json fit.slope .1f provenance=false`; "
        "see [](#fig-plot) and [](#tbl-data).\n\n"
        ":::{cktable} data/clean.csv\n:name: tbl-data\n"
        "The data.\n:::\n"
    )
    config = "version: 1\nproject:\n  title: Site\n"
    (tmp_path / "site" / "myst.yml").write_text(config)
    # The environment has to be named, and the plugin listed
    res = build()
    assert res.returncode != 0
    assert "Name the environment" in res.stdout + res.stderr
    res = build("-e", "_system")
    assert res.returncode != 0
    assert calkit.myst.PLUGIN_CONFIG in res.stdout + res.stderr
    (tmp_path / "site" / "myst.yml").write_text(
        config + "  plugins:\n    - _extensions/calkit/myst.mjs\n"
    )
    # What it shows, values included, has to be among the stage's inputs,
    # so it rebuilds
    subprocess.check_call(["git", "add", "-A"], cwd=tmp_path)
    subprocess.check_call(
        [
            "git",
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-qm",
            "Add project",
        ],
        cwd=tmp_path,
    )
    res = subprocess.run(
        ["calkit", "run"], capture_output=True, text=True, cwd=tmp_path
    )
    assert res.returncode != 0
    assert "add to its inputs: ../results/fit.json" in res.stdout + res.stderr
    ck_info["pipeline"]["stages"]["site"]["inputs"] = site_inputs
    with open(tmp_path / "calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"], cwd=tmp_path)
    assert (tmp_path / "site" / calkit.myst.PLUGIN_PATH).is_file()
    text = read_export()
    # MyST numbers and refers to what it shows
    assert ":::{figure} ../figures/plot.svg\n:name: fig-plot" in text
    assert "see [Figure 1](#fig-plot) and [Table 1](#tbl-data)." in text
    assert ":::{list-table} The data.\n:header-rows: 1\n:name: tbl-data" in (
        text
    )
    # Each component's provenance is collapsed under it, quietly, and the
    # values' at the end, which they mark and link to, except one with it
    # turned off
    assert get_summaries(text) == [
        "Provenance",
        "Provenance",
        "Where the values came from",
    ]
    assert re.search(
        r"The slope is 0\.123\[\{sup\}`ⓘ`\]\(#ck-value-[\w-]+\), "
        r"k is 0\.031\[\{sup\}`ⓘ`\]\(#ck-value-[\w-]+\), "
        r"sigma is 0\.1\[\{sup\}`ⓘ`\]\(#ck-value-[\w-]+\), "
        r"and not shown, 0\.1;",
        text,
    ), text
    # Expanded, it's how it came to be, with a graph of only what it's
    # made from, and links to the repo's host and the document
    figure_view = text.split(":::{dropdown} Provenance")[1].split("\n:::")[0]
    assert 's0[["clean"]]' in figure_view and "fit" not in figure_view
    assert "https://github.com/example/proj/blob/" in figure_view
    assert "Makes [`data/clean.csv`](#tbl-data)" in figure_view
    values_view = text.split("{dropdown} Where the values came from")[1]
    assert "`k_25`, saved from a cell of" in values_view
    assert "**Stage** `fit` (jupyter-notebook)" in values_view
    assert "`sigma`, quoted from reference `liu2025`" in values_view
    assert "Recorded as 0.1, on page 4" in values_view
    # An edited script makes what's made from it out of date, said while
    # collapsed, and marked inline for a value
    with open(tmp_path / "scripts" / "clean.py", "a") as f:
        f.write("# Edited\n")
    res = build("-e", "_system", "--", "index.md", "--md", "--ci")
    assert res.returncode == 0, res.stdout + res.stderr
    text = read_export()
    assert get_summaries(text)[:2] == [
        "⚠️ Out of date: waiting on data/clean.csv",
        "⚠️ Out of date: scripts/clean.py modified",
    ]
    assert re.search(r"The slope is 0\.123\[\{sup\}`⚠`\]", text)
    # Built without Calkit after the document changed, it says so
    record_path = tmp_path / calkit.quarto.get_provenance_path("site/index.md")
    with open(tmp_path / "site" / "index.md", "a") as f:
        f.write("\nMore text.\n")
    subprocess.check_call(
        ["myst", "build", "index.md", "--md", "--ci"], cwd=tmp_path / "site"
    )
    text = read_export()
    assert all(
        s.endswith("recorded before this document changed")
        for s in get_summaries(text)[:2]
    )
    # With nothing recorded, it says so, still numbering and referring to
    # the table, and values can't be shown, since MyST doesn't read them
    record = json.loads(record_path.read_text())
    assert set(record["roles"]) == {"ckvalue", "ckrefval"}
    record_path.unlink()
    subprocess.check_call(
        ["myst", "build", "index.md", "--md", "--ci"], cwd=tmp_path / "site"
    )
    text = read_export()
    assert get_summaries(text) == ["⚠️ No provenance recorded"] * 2
    assert "[Table 1](#tbl-data)" in text
    assert "The slope is ??" in text
    # A record is removed with what it was for
    res = build("-e", "_system", "--", "index.md", "--md", "--ci")
    assert res.returncode == 0, res.stdout + res.stderr
    assert record_path.is_file()
    (tmp_path / "site" / "index.md").write_text("# Report\n\nNo panels.\n")
    res = build("-e", "_system", "--", "index.md", "--md", "--ci")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not record_path.exists()
