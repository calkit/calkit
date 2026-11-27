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

    def read_export(name: str = "index.md") -> str:
        with open(tmp_path / "site" / "_build" / "exports" / name) as f:
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
        "page2.md",
        "parts/a.md",
        "parts/b.md",
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
                "command": (
                    "calkit myst build -e _system -- "
                    "index.md page2.md --md --ci"
                ),
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
        "The data.\n:::\n\n"
        ":::{include} parts/a.md\n:::\n"
    )
    # Includes are read relative to the file including them, and a value on
    # another page links to its own view
    (tmp_path / "site" / "parts").mkdir()
    (tmp_path / "site" / "parts" / "a.md").write_text(
        "Part A.\n\n:::{include} b.md\n:::\n"
    )
    (tmp_path / "site" / "parts" / "b.md").write_text(
        "Part B {ckvalue}`results/fit.json fit.slope .4f`.\n"
    )
    (tmp_path / "site" / "page2.md").write_text(
        "# Page 2\n\nAgain {ckvalue}`results/fit.json fit.slope .3f`.\n"
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
    # On the host, as far as this clone knows, so files link there
    subprocess.check_call(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path
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
    # values' are each collapsed at the end, which they mark and link to,
    # except one with it turned off
    assert get_summaries(text) == ["Provenance", "Provenance"]
    marks = re.findall(
        r"(\d\.\d+)\[\{abbr\}``\{sup\}`(.)` \(Where [\d.]+ came from: "
        r"([^)]*)\)``\]\(#(ck-value-\w+)\)",
        text,
    )
    assert [(v, m, s) for v, m, s, _ in marks] == [
        ("0.123", "†", "Provenance"),
        ("0.031", "†", "Provenance"),
        ("0.1", "†", "Provenance"),
    ]
    assert "and not shown, 0.1;" in text
    views = re.findall(
        r"^:{3,}\{(note|warning)\} (.*)\n:class: (.*)$", text, re.M
    )
    assert views[0][0] == "note"
    assert views[0][2] == "dropdown ck-provenance ck-ok"
    assert views[0][1].startswith(
        "`fit.slope` in [`results/fit.json`](https://github.com/example/proj/"
    )
    # Titled by only what it is while all's well
    assert views[0][1].endswith(")")
    assert "`k_25`, saved from a cell of" in views[1][1]
    assert "**Stage** `fit` (jupyter-notebook)" in text
    assert "`sigma`, quoted from reference `liu2025`" in views[2][1]
    assert "Recorded as 0.1, on page 4" in text
    # Unique to its page
    page2 = read_export("page2.md")
    page2_ids = re.findall(r"\]\(#(ck-value-\w+)\)", page2)
    assert page2_ids and page2_ids[0] != marks[0][3]
    # What's included, however deep, counts
    record_path = tmp_path / calkit.quarto.get_provenance_path("site/index.md")
    record = json.loads(record_path.read_text())
    assert "results/fit.json fit.slope .4f" in record["roles"]["ckvalue"]
    # Expanded, it's how it came to be, with a graph of only what it's
    # made from, and links to the repo's host and the document
    figure_view = text.split(":::{dropdown} Provenance")[1].split("\n:::")[0]
    assert 's0[["clean"]]' in figure_view and "fit" not in figure_view
    assert "https://github.com/example/proj/blob/" in figure_view
    assert "Makes [`data/clean.csv`](#tbl-data)" in figure_view
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
    assert re.search(r"The slope is 0\.123\[\{abbr\}``\{sup\}`!`", text)
    # Built without Calkit after a file it shows changed, a table shows the
    # file as it is, and a value as it was recorded, both saying it changed
    # since
    (tmp_path / "data" / "clean.csv").write_text("x,y\n7,8\n")
    (tmp_path / "results" / "fit.json").write_text('{"fit": {"slope": 0.5}}')
    subprocess.check_call(
        ["myst", "build", "index.md", "--md", "--ci"], cwd=tmp_path / "site"
    )
    text = read_export()
    assert get_summaries(text)[1] == (
        "⚠️ Out of date: scripts/clean.py modified · recorded before "
        "data/clean.csv changed"
    )
    assert "*   *   7" in text
    assert re.search(
        r"The slope is 0\.123\[\{abbr\}``\{sup\}`!` \(Where 0\.123 came "
        r"from: [^)]*recorded before results/fit\.json changed\)",
        text,
    )
    assert re.search(
        r"^:{3,}\{warning\} `fit\.slope` in .*: ⚠️ Out of date: .* "
        r"recorded before results/fit\.json changed\n"
        r":class: dropdown ck-provenance$",
        text,
        re.M,
    )
    # Built without Calkit after the document changed, it says so
    with open(tmp_path / "site" / "index.md", "a") as f:
        f.write("\nMore text.\n")
    subprocess.check_call(
        ["myst", "build", "index.md", "--md", "--ci"], cwd=tmp_path / "site"
    )
    text = read_export()
    assert get_summaries(text)[0].endswith(
        "recorded before this document changed"
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
    # Its rows, which are read from the file
    assert "*   *   7" in text
    assert "The slope is ??" in text
    # A record is removed with what it was for
    res = build("-e", "_system", "--", "index.md", "--md", "--ci")
    assert res.returncode == 0, res.stdout + res.stderr
    assert record_path.is_file()
    (tmp_path / "site" / "index.md").write_text("# Report\n\nNo panels.\n")
    res = build("-e", "_system", "--", "index.md", "--md", "--ci")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not record_path.exists()
