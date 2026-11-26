"""Tests for ``calkit.cli.myst``."""

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
    def build(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "myst", "build", *args],
            capture_output=True,
            text=True,
            cwd=tmp_path / "site",
        )

    def get_titles() -> list[str]:
        with open(tmp_path / "site" / "_build" / "exports" / "index.md") as f:
            return re.findall(
                r"^:::\{(?:note|warning|danger)\} (.*)$", f.read(), re.M
            )

    subprocess.check_call(["calkit", "init"], cwd=tmp_path)
    for folder in ["scripts", "data", "figures", "site"]:
        (tmp_path / folder).mkdir()
    (tmp_path / "data" / "raw.csv").write_text("x,y\n1,2\n3,4\n")
    (tmp_path / "scripts" / "clean.py").write_text(
        "import shutil\nshutil.copy('data/raw.csv', 'data/clean.csv')\n"
    )
    (tmp_path / "scripts" / "plot.py").write_text(
        "open('figures/plot.svg', 'w').write(\n"
        '    \'<svg xmlns="http://www.w3.org/2000/svg" width="10" '
        'height="10"/>\'\n)\n'
    )
    stage = {"kind": "python-script", "environment": "_system"}
    ck_info: dict = {
        "requirements": ["myst"],
        "datasets": [{"path": "data/raw.csv", "created_by": {"name": "Jo"}}],
        "pipeline": {
            "stages": {
                "clean": {
                    **stage,
                    "script_path": "scripts/clean.py",
                    "inputs": ["data/raw.csv"],
                    "outputs": [{"path": "data/clean.csv", "storage": "git"}],
                },
                "plot": {
                    **stage,
                    "script_path": "scripts/plot.py",
                    "inputs": ["data/clean.csv"],
                    "outputs": [
                        {"path": "figures/plot.svg", "storage": "git"}
                    ],
                },
                "site": {
                    "kind": "command",
                    "wdir": "site",
                    "command": (
                        "calkit myst build -e _system -- index.md --md --ci"
                    ),
                    "environment": "_system",
                    "inputs": [
                        "index.md",
                        "myst.yml",
                        "../figures/plot.svg",
                        "../data/clean.csv",
                    ],
                    "outputs": ["_build/exports"],
                },
            }
        },
    }
    with open(tmp_path / "calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # With a directive in backticks first, whose closing fence doesn't open
    # a code block
    (tmp_path / "site" / "index.md").write_text(
        "# Report\n\n```{tip}\nA tip.\n```\n\n"
        ":::{ckprovenance} ../figures/plot.svg\n:label: fig-plot\n"
        "The plot.\n:::\n\n"
        "See [](#fig-plot) and [](#tbl-data).\n\n"
        ":::{ckprovenance} ../data/clean.csv\n:name: tbl-data\n"
        "The data.\n:::\n\n"
        ":::{ckprovenance}\n:graph: false\n:::\n"
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
    # What it shows has to be among the stage's inputs, so it rebuilds
    site_stage = ck_info["pipeline"]["stages"]["site"]
    site_stage["inputs"] = site_stage["inputs"][:-1]
    with open(tmp_path / "calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = subprocess.run(
        ["calkit", "run"], capture_output=True, text=True, cwd=tmp_path
    )
    assert res.returncode != 0
    assert "add to its inputs: ../data/clean.csv" in res.stdout + res.stderr
    site_stage["inputs"].append("../data/clean.csv")
    with open(tmp_path / "calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"], cwd=tmp_path)
    assert (tmp_path / "site" / calkit.myst.PLUGIN_PATH).is_file()
    # MyST numbers and refers to what it shows, so it's a figure and table,
    # with non-breaking spaces as plain ones
    with open(tmp_path / "site" / "_build" / "exports" / "index.md") as f:
        text = f.read().replace("\xa0", " ")
    assert ":::{figure} ../figures/plot.svg\n:name: fig-plot" in text
    assert "See [Figure 1](#fig-plot) and [Table 1](#tbl-data)." in text
    assert (
        ":::{list-table} The data.\n:header-rows: 1\n:name: tbl-data" in text
    )
    # It says the same as for Quarto, leaving out the site's own output
    # and a section turned off
    assert get_titles() == [
        "Figure up to date",
        "Table up to date",
        "Document up to date",
    ]
    assert "**Not checked:** `site/_build/exports`" in text
    assert "flowchart" not in text
    # An edited script makes what's made from it out of date
    with open(tmp_path / "scripts" / "clean.py", "a") as f:
        f.write("# Edited\n")
    res = build("-e", "_system", "--", "index.md", "--md", "--ci")
    assert res.returncode == 0, res.stdout + res.stderr
    assert get_titles() == [
        "Figure out of date: waiting on data/clean.csv",
        "Table out of date: scripts/clean.py modified",
        "Document out of date: 2 of 2 outputs",
    ]
    # Built without Calkit after the document changed, it says so
    with open(tmp_path / "site" / "index.md", "a") as f:
        f.write("\nMore text.\n")
    subprocess.check_call(
        ["myst", "build", "index.md", "--md", "--ci"],
        cwd=tmp_path / "site",
    )
    assert get_titles().count("Document changed since panels recorded") == 3
    # As it does with nothing recorded, still numbering and referring to
    # the table
    record_path = tmp_path / calkit.quarto.get_provenance_path("site/index.md")
    record_path.unlink()
    subprocess.check_call(
        ["myst", "build", "index.md", "--md", "--ci"],
        cwd=tmp_path / "site",
    )
    assert get_titles() == ["No provenance recorded"] * 3
    with open(tmp_path / "site" / "_build" / "exports" / "index.md") as f:
        text = f.read().replace("\xa0", " ")
    assert "See [Figure 1](#fig-plot) and [Table 1](#tbl-data)." in text
    # A record is removed with the directives it was for
    res = build("-e", "_system", "--", "index.md", "--md", "--ci")
    assert res.returncode == 0, res.stdout + res.stderr
    assert record_path.is_file()
    (tmp_path / "site" / "index.md").write_text("# Report\n\nNo panels.\n")
    res = build("-e", "_system", "--", "index.md", "--md", "--ci")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not record_path.exists()
