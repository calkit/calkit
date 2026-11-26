"""Tests for ``calkit.quarto``."""

import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import calkit.dvc
import calkit.quarto
from calkit.markdown import MarkdownParseError


def test_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results.json").write_text(
        json.dumps({"rms": 0.123456, "fit": {"n": 401, "coeffs": [1.5, 2]}})
    )
    (tmp_path / "metrics.yaml").write_text("speed: 3.25\n")
    # A notebook's shortcodes are in its Markdown and raw cells, not its code
    nb = {
        "cells": [
            {"cell_type": "markdown", "source": ["The RMS is\n", "{{< "]},
            {"cell_type": "code", "source": "{{< ckvalue code.json x >}}"},
            {"cell_type": "raw", "source": "{{< ckvalue results.json rms >}}"},
        ]
    }
    (tmp_path / "doc.ipynb").write_text(json.dumps(nb))
    text = calkit.quarto.read_document_text("doc.ipynb")
    assert text == "The RMS is\n{{< \n{{< ckvalue results.json rms >}}"
    assert calkit.quarto.read_document_text("missing.qmd") is None
    # Arguments read like the Markdown marker's, positionally or by name,
    # with a declared result's name standing for its path
    text = (
        "RMS {{< ckvalue results.json rms .2f >}} over "
        "{{< ckvalue key=fit.n path=results.json >}} samples\n"
        "at {{< ckvalue speed key=speed format='{value:.1f} m/s' >}}; "
        "{{</* ckvalue escaped.json x */>}}\n"
        "{{< ckvalue results.json fit.coeffs.0 .1% >}}\n"
    )
    values = calkit.quarto.extract_values(
        text, "doc.qmd", results={"speed": "metrics.yaml"}
    )
    assert [(v.path, v.key, v.format, v.line) for v in values] == [
        ("results.json", "rms", ".2f", 1),
        ("results.json", "fit.n", None, 1),
        ("metrics.yaml", "speed", "{value:.1f} m/s", 2),
        ("results.json", "fit.coeffs.0", ".1%", 3),
    ]
    # Each is shown as Python formats it
    assert calkit.quarto.check_values(values, "doc.qmd") == [
        "0.12",
        "401",
        "3.2 m/s",
        "150.0%",
    ]
    # A notebook stands for the values its cells save
    fit_values = calkit.quarto.extract_values(
        "{{< ckvalue nbs/fit.ipynb k_25 .3f >}}", "doc.qmd"
    )
    assert fit_values[0].path == (
        ".calkit/notebooks/outputs/nbs/fit.ipynb/values.json"
    )
    with pytest.raises(MarkdownParseError, match="No values saved from"):
        calkit.quarto.check_values(fit_values, "doc.qmd")
    (tmp_path / fit_values[0].path).parent.mkdir(parents=True)
    (tmp_path / fit_values[0].path).write_text(json.dumps({"k_25": 0.030912}))
    assert calkit.quarto.check_values(fit_values, "doc.qmd") == ["0.031"]
    # Mistakes name their line
    with pytest.raises(MarkdownParseError, match="names no key"):
        calkit.quarto.extract_values("\n{{< ckvalue a.json >}}", "doc.qmd")
    with pytest.raises(MarkdownParseError, match="doesn't exist"):
        calkit.quarto.check_values(
            calkit.quarto.extract_values(
                "{{< ckvalue gone.json x >}}", "doc.qmd"
            ),
            "doc.qmd",
        )
    with pytest.raises(MarkdownParseError, match="has no key 'nope'"):
        calkit.quarto.check_values(
            calkit.quarto.extract_values(
                "{{< ckvalue results.json nope >}}", "doc.qmd"
            ),
            "doc.qmd",
        )
    # As are what the shortcode can't read or format the way Python does,
    # including YAML text that Pandoc, which reads it, would change
    (tmp_path / "text.yaml").write_text(
        "version: '1.50'\nemphasis: a *b*\npath: 'C:\\data'\nname: run_a\n"
    )
    assert calkit.quarto.check_values(
        calkit.quarto.extract_values(
            "{{< ckvalue text.yaml name >}}", "doc.qmd"
        ),
        "doc.qmd",
    ) == ["run_a"]
    for text, match in [
        ("{{< ckvalue results.json rms ' .2f' >}}", "can't format"),
        ("{{< ckvalue results.json rms 8.2f >}}", "can't format"),
        ("{{< ckvalue results.json rms '{x:.2f}' >}}", "can't format"),
        ("{{< ckvalue results.json rms d >}}", "Can't format 'rms'"),
        ("{{< ckvalue results.json fit >}}", "list or table"),
        ("{{< ckvalue text.yaml version >}}", "looks like a number"),
        ("{{< ckvalue text.yaml emphasis >}}", "reads as Markdown"),
        ("{{< ckvalue text.yaml path >}}", "reads as Markdown"),
    ]:
        with pytest.raises(MarkdownParseError, match=match):
            calkit.quarto.check_values(
                calkit.quarto.extract_values(text, "doc.qmd"), "doc.qmd"
            )
    # Embedded documents are found relative to the document, or to its
    # Quarto project with a leading slash, which is its folder without one
    text = (
        "{{< embed ../analysis.ipynb#fig-decay >}}\n"
        '{{< embed "/analysis.ipynb#tbl-fit" >}}\n'
        "{{< embed notes.qmd >}} {{</* embed escaped.ipynb */>}}\n"
    )
    assert calkit.quarto.extract_embedded_paths(text, "pub/doc.qmd") == [
        "analysis.ipynb",
        "pub/analysis.ipynb",
        "pub/notes.qmd",
    ]
    # Without a Quarto project, the extension is written beside the
    # document, and left alone when already right
    (tmp_path / "pub").mkdir()
    calkit.quarto.write_components("pub/index.ipynb")
    ext = tmp_path / "pub" / "_extensions" / "calkit"
    assert (ext / "calkit.lua").read_text() == calkit.quarto.SHORTCODE_LUA
    assert "calkit.lua" in (ext / "_extension.yml").read_text()
    assert not (tmp_path / "pub" / "_calkit").exists()
    mtime = (ext / "calkit.lua").stat().st_mtime_ns
    calkit.quarto.write_components("pub/index.ipynb")
    assert (ext / "calkit.lua").stat().st_mtime_ns == mtime
    # In one, at its root, relative to wdir
    (tmp_path / "site" / "pages").mkdir(parents=True)
    (tmp_path / "site" / "_quarto.yml").write_text(
        "project:\n  type: website\n"
    )
    monkeypatch.chdir(tmp_path / "pub")
    calkit.quarto.write_components("site/pages/about.qmd", wdir=str(tmp_path))
    assert (
        tmp_path / "site" / "_extensions" / "calkit" / "calkit.lua"
    ).is_file()
    # A Quarto project at wdir counts, and the search stops there
    assert calkit.quarto.get_quarto_dir("site/a.qmd", str(tmp_path)) == "site"
    (tmp_path / "_quarto.yml").write_text("")
    assert calkit.quarto.get_quarto_dir("pub/a.qmd", str(tmp_path)) == ""
    assert calkit.quarto.get_quarto_dir("a.qmd", str(tmp_path / "pub")) == ""


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs Quarto")
def test_shortcode_matches_python(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "r.json").write_text(
        json.dumps(
            {
                "rms": 0.123456,
                "n": 1234567,
                "neg": -0.000012345,
                "big": 1e16,
                "fifteen": 1e15,
                "whole": 19.0,
                "fit": {"coeffs": [1.5, 2, -3.25], "25": 0.0309},
                "flag": True,
                "name": "alpha",
                "negzero": -0.0,
                "x": 1234.5,
            }
        )
    )
    # With what Pandoc, which reads YAML for Quarto, sees differently, e.g.,
    # a document marker, or numbers it rewrites
    (tmp_path / "results" / "m.yaml").write_text(
        "\n---\nspeed: 3.25\ncount: 401\nnested:\n  list: [1, 2.5]\n"
        "trailing: 1.50\nsmall: 1.0e-3\nbig: .inf\nlabel: it's -- done...\n"
    )
    (tmp_path / "calkit.yaml").write_text(
        "\n# Project\nresults:\n  - name: metrics\n    path: results/m.yaml\n"
    )
    (tmp_path / "results" / "t.toml").write_text(
        "# Results\n"
        'title = "Run \\"A\\" \\u00e9"\n'
        "path = 'C:\\data'\n"
        "n = 1_234\n"
        "mask = 0xff\n"
        "rate = 6.5e-3  # per second\n"
        "whole = 2.0\n"
        "big = inf\n"
        "on = true\n"
        "fit.r2 = 0.987\n"
        'notes = """\nfirst\nsecond"""\n'
        "coeffs = [\n  1.5, # a\n  -2,\n]\n"
        "point = { x = 1, y.z = 2.5 }\n"
        "\n[case.'quoted']\nspeed = 12.25\n"
        "\n[[runs]]\nscore = 0.5\n"
        "\n[[runs]]\nscore = 0.75\n[runs.meta]\nseed = 7\n"
    )
    cases = [
        ("results/r.json", "rms", f)
        for f in ["", ".2f", ".3e", ".1%", "+.2f", "g", ".3g", "E", "%"]
    ]
    cases += [
        ("results/r.json", "n", f) for f in ["", ",", ",d", "_d", ",.2f"]
    ]
    cases += [
        ("results/r.json", key, "")
        for key in ["neg", "big", "fifteen", "whole", "flag", "negzero"]
    ]
    nb_values_path = tmp_path / ".calkit/notebooks/outputs/nbs/fit.ipynb"
    nb_values_path.mkdir(parents=True)
    (nb_values_path / "values.json").write_text(
        json.dumps({"k_25": 0.030912, "rates": {"25": 0.031}})
    )
    cases += [
        ("nbs/fit.ipynb", "k_25", ".3f"),
        ("nbs/fit.ipynb", "rates.25", ".1%"),
        ("results/r.json", "fit.coeffs.0", ".1%"),
        ("results/r.json", "fit.coeffs.-1", ""),
        ("results/r.json", "fit.25", ".3f"),
        ("results/r.json", "name", "s"),
        ("results/r.json", "x", "{value:.1f} m/s"),
        ("results/r.json", "x", "{0:.0f} and {value:,.2f}"),
        ("results/t.toml", "title", ""),
        ("results/t.toml", "path", ""),
        ("results/t.toml", "n", ",d"),
        ("results/t.toml", "mask", ""),
        ("results/t.toml", "rate", ".2e"),
        ("results/t.toml", "whole", ""),
        ("results/t.toml", "big", ""),
        ("results/t.toml", "on", ""),
        ("results/t.toml", "fit.r2", ".2f"),
        ("results/t.toml", "coeffs.1", ""),
        ("results/t.toml", "point.y.z", ""),
        ("results/t.toml", "case.quoted.speed", ".1f"),
        ("results/t.toml", "runs.1.score", ".0%"),
        ("results/t.toml", "runs.1.meta.seed", ""),
        ("metrics", "speed", ".1f"),
        ("metrics", "count", ",d"),
        ("metrics", "nested.list.1", ".2f"),
        ("metrics", "trailing", ""),
        ("metrics", "trailing", "+"),
        ("metrics", "small", ""),
        ("metrics", "big", ""),
        ("metrics", "label", ""),
    ]
    # In a folder below the project, since paths are relative to it
    (tmp_path / "docs").mkdir()
    lines = []
    for i, (source, key, fmt) in enumerate(cases):
        source = source if source == "metrics" else f"path={source}"
        fmt = f" format='{fmt}'" if fmt else ""
        lines.append(f"V{i}: {{{{< ckvalue {source} key={key}{fmt} >}}}}")
    lines.append("Gone: {{< ckvalue results/gone.json x >}}")
    (tmp_path / "docs" / "doc.qmd").write_text("\n\n".join(lines) + "\n")
    values = calkit.quarto.extract_values(
        "\n".join(lines[:-1]),
        "docs/doc.qmd",
        results={"metrics": "results/m.yaml"},
    )
    expected = calkit.quarto.check_values(values, "docs/doc.qmd")
    calkit.quarto.write_components("docs/doc.qmd")
    subprocess.check_call(
        ["quarto", "render", "doc.qmd", "--to", "plain"], cwd="docs"
    )
    got = (tmp_path / "docs" / "doc.txt").read_text().strip().split("\n\n")
    assert [line.split(": ", 1)[1].strip() for line in got[:-1]] == expected
    # A value that can't be read shows as missing
    assert got[-1].strip() == "Gone: ??"


def test_refvals(tmp_path):
    # A value quoted from a reference is read from the file Calkit writes
    # its reference's values to, by name, in document order
    from calkit.references.values import get_values_path, write_values_file

    path = get_values_path("liu.2025")

    text = (
        "Noise of {{< ckrefval liu.2025 noise-sigma .2f >}} "
        "[@liu.2025], and {{< ckvalue results/r.json rms >}}.\n"
        "Again {{< ckrefval liu.2025 noise-sigma format=.1f >}}.\n"
    )
    values = calkit.quarto.extract_values(text, "index.qmd")
    assert [(v.path, v.key, v.format, v.ref) for v in values] == [
        (path, "noise-sigma", ".2f", ("liu.2025", "noise-sigma")),
        ("results/r.json", "rms", None, None),
        (path, "noise-sigma", ".1f", ("liu.2025", "noise-sigma")),
    ]
    refvals = [v for v in values if v.ref]
    with pytest.raises(MarkdownParseError, match="records no value"):
        calkit.quarto.check_values(refvals, "index.qmd", wdir=str(tmp_path))
    write_values_file(
        {
            "references": [
                {
                    "path": "r.bib",
                    "values": {"liu.2025": {"noise-sigma": {"value": 0.1}}},
                }
            ]
        },
        wdir=str(tmp_path),
    )
    calkit.quarto.check_values(refvals, "index.qmd", wdir=str(tmp_path))
    missing = calkit.quarto.extract_values(
        "{{< ckrefval liu.2025 other >}}", "index.qmd"
    )
    with pytest.raises(
        MarkdownParseError,
        match="calkit.yaml records no value 'other' quoted from 'liu.2025'",
    ):
        calkit.quarto.check_values(missing, "index.qmd", wdir=str(tmp_path))
    with pytest.raises(MarkdownParseError, match="takes a citation key"):
        calkit.quarto.extract_values(
            "{{< ckrefval path=liu.2025 key=x >}}", "index.qmd"
        )


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs Quarto")
def test_refval_shortcode(tmp_path, monkeypatch):
    # Quarto renders the shortcode itself, finding the file of a
    # reference's values as Python names it, whatever the key, and a
    # missing one as ??
    from calkit.references.values import write_values_file

    monkeypatch.chdir(tmp_path)
    (tmp_path / "calkit.yaml").write_text("name: t\n")
    write_values_file(
        {
            "references": [
                {
                    "path": "r.bib",
                    "values": {
                        "liu.2025": {
                            "noise-sigma": {"value": 0.1},
                            "label": {"value": "α"},
                        },
                        "smith:2020/b+é": {"n": {"value": 7}},
                    },
                }
            ]
        },
        wdir=str(tmp_path),
    )
    (tmp_path / "index.qmd").write_text(
        "---\ntitle: T\n---\n\n"
        "A {{< ckrefval liu.2025 noise-sigma .2f >}} "
        "B {{< ckrefval liu.2025 label >}} "
        "C {{< ckrefval liu.2025 nope >}} "
        "D {{< ckrefval liu.2025 key=noise-sigma format=.1f >}} "
        "E {{< ckrefval smith:2020/b+é n >}}\n"
    )
    calkit.quarto.write_components("index.qmd", wdir=str(tmp_path))
    subprocess.check_call(
        ["quarto", "render", "index.qmd", "--to", "md"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    out = (tmp_path / "index.md").read_text()
    assert "A 0.10 B α C ?? D 0.1 E 7" in out


def test_provenance_panels(tmp_path: Path) -> None:
    def get_titles(node: dict) -> list[str]:
        titles = [t["value"] for t in node.get("title", [])]
        for child in node.get("children") or []:
            if isinstance(child, dict):
                titles += get_titles(child)
        return titles

    def get_text(node: dict | list) -> str:
        if isinstance(node, list):
            return "".join(get_text(n) for n in node)
        out = (
            str(node.get("value", ""))
            if node.get("type") != "admonition"
            else ""
        )
        for key in ("title", "children"):
            out += get_text(node.get(key) or [])
        return out + (
            "\n" if node.get("type") in ("paragraph", "tableRow") else ""
        )

    # Divs are found outside code, with a src relative to the document, or
    # its Quarto project with a leading slash, shown as their extension says
    # unless they say otherwise
    (tmp_path / "pub").mkdir()
    (tmp_path / "pub" / "_quarto.yml").write_text(
        "project:\n  type: default\n"
    )
    text = (
        '::: {.ckprovenance src="../figures/plot.svg" #fig-plot width="50%"}\n'
        "Caption\n:::\n"
        "```markdown\n::: {.ckprovenance src=in-code.png}\n```\n"
        "::: {#tbl-data .ckprovenance src='/data.csv' rows=2}\n:::\n"
        "::: {.ckprovenance src=notes.txt kind=table}\n:::\n"
        "::: {.callout-note src=other.png}\n:::\n"
        "::: ckprovenance\n:::\n"
    )
    divs = calkit.quarto.extract_provenance_divs(
        text, "pub/pages/doc.qmd", wdir=str(tmp_path)
    )
    assert [(d.src, d.path, d.kind, d.line, d.rows) for d in divs] == [
        ("../figures/plot.svg", "pub/figures/plot.svg", "figure", 1, 25),
        ("/data.csv", "pub/data.csv", "table", 7, 2),
        ("notes.txt", "pub/pages/notes.txt", "table", 9, 25),
        ("", "", "document", 13, 25),
    ]
    # A project: raw data cleaned, then plotted, and rendered in a report
    ck_info = {
        "datasets": [
            {"path": "data/raw.csv", "created_by": {"name": "Jane Doe"}},
        ],
        "figures": [
            {
                "path": "figures/photo.png",
                "imported_from": {"url": "https://example.com/photo.png"},
            }
        ],
        "environments": {"py": {"kind": "uv-venv", "path": "reqs.txt"}},
        "pipeline": {
            "stages": {
                "clean": {"kind": "python-script", "environment": "py"},
                "plot": {"kind": "python-script", "environment": "py"},
                "report": {
                    "kind": "quarto",
                    "target_path": "report.qmd",
                    "environment": "_system",
                },
            }
        },
    }

    def get_entry(path: str) -> dict:
        return {"path": path, "hash": "md5", "md5": path + "-1"}

    dvc_stages = {
        "clean": {"cmd": "python scripts/clean.py"},
        "plot": {"cmd": "python scripts/plot.py"},
        "report": {"cmd": "calkit quarto render report.qmd"},
        "gone": {"cmd": "echo"},
    }
    lock_stages: dict[str, dict] = {
        "clean": {
            "cmd": "python scripts/clean.py",
            "deps": [get_entry("scripts/clean.py"), get_entry("data/raw.csv")],
            "outs": [get_entry("data/clean.csv")],
        },
        "plot": {
            "cmd": "python scripts/plot.py",
            "deps": [
                get_entry("scripts/plot.py"),
                get_entry("data/clean.csv"),
                get_entry(".calkit/env-locks/py.txt"),
            ],
            "outs": [get_entry("figures/plot.svg")],
        },
        "report": {
            "cmd": "calkit quarto render report.qmd",
            "deps": [
                get_entry("report.qmd"),
                get_entry("figures/plot.svg"),
                get_entry("data/clean.csv"),
                get_entry("figures/photo.png"),
            ],
            "outs": [get_entry("report.html")],
        },
    }
    stage_runs = {
        "plot": {
            "start_time": "2026-11-20T10:00:00",
            "git_rev": "abcdef123456",
            "git_dirty": False,
            "system": {"os": "Linux", "machine": "x86_64"},
            "dvc_lock_hash": calkit.dvc.stage_lock_hash(lock_stages["plot"]),
        },
        # A run that isn't the one dvc.lock records isn't shown
        "clean": {"start_time": "2026-11-19T10:00:00", "dvc_lock_hash": "x"},
        # Nor is the document's own, since it's running
        "report": {
            "start_time": "2026-11-20T10:00:00",
            "dvc_lock_hash": calkit.dvc.stage_lock_hash(lock_stages["report"]),
        },
    }
    files = {
        entry["path"]: entry["md5"]
        for stage in lock_stages.values()
        for entry in stage["deps"] + stage["outs"]
    }
    files["data/clean.csv"] = "data/clean.csv-1"
    content = {"data/clean.csv": "x,y\n1,2\n3,4\n5,6\n"}
    up_to_date = {
        "status": "up-to-date",
        "modified_command": False,
        "modified_inputs": [],
        "modified_outputs": [],
        "missing_outputs": [],
    }

    def get_panels(
        text: str,
        hashes: dict,
        document_path: str = "report.qmd",
        document_stage: str | None = None,
        statuses: dict[str, dict] | None = None,
    ) -> dict:
        return calkit.quarto.get_provenance_panels(
            calkit.quarto.extract_provenance_divs(text, document_path),
            document_path,
            document_stage=document_stage,
            ck_info=ck_info,
            dvc_yaml={"stages": dvc_stages},
            dvc_lock={"stages": lock_stages},
            stage_runs=stage_runs,
            get_stage_status=lambda name: {
                **up_to_date,
                **(statuses or {}).get(name, {}),
            },
            is_file=lambda p: p in hashes,
            is_dir=lambda p: False,
            listdir=lambda p: [],
            read_bytes=lambda p: content[p].encode(),
            open_text=lambda p: io.StringIO(content[p]),
        )

    text = (
        "::: {.ckprovenance src=figures/plot.svg #fig-plot}\n:::\n"
        "::: {.ckprovenance src=data/clean.csv rows=2}\n:::\n"
        "::: {.ckprovenance src=figures/photo.png}\n:::\n"
        "::: {.ckprovenance src=figures/sketch.png}\n:::\n"
        "::: {.ckprovenance src=figures/gone.png}\n:::\n"
        "::: {.ckprovenance}\n:::\n"
    )
    files["figures/sketch.png"] = "s"
    res = get_panels(text, files)
    panels = res["panels"]
    assert list(panels) == [
        "figures/plot.svg",
        "data/clean.csv",
        "figures/photo.png",
        "figures/sketch.png",
        "figures/gone.png",
    ]
    plot = panels["figures/plot.svg"]
    assert (plot["kind"], plot["body"]) == ("figure", [])
    assert plot["panel"][0]["kind"] == "note"
    assert plot["panel"][0]["dropdown"]
    plot_text = get_text(plot["panel"])
    assert plot_text.startswith("Figure up to date")
    assert "Made by: stage plot, python-script\n" in plot_text
    assert "Environment: py (uv-venv)\n" in plot_text
    assert "Last run: 2026-11-20, Linux x86_64, commit abcdef1\n" in plot_text
    # Its script first, without Calkit's bookkeeping, e.g., its
    # environment's lock
    assert (
        "scripts/plot.py✅ unchanged\ndata/clean.csvclean✅ unchanged\n"
        in (plot_text)
    )
    assert ".calkit" not in plot_text
    # A table is shown cut short, and a run not recorded in dvc.lock says
    # so, e.g., one since the pipeline started
    table = panels["data/clean.csv"]
    assert table["kind"] == "table"
    assert (
        get_text(table["body"])
        == "xy\n12\n34\nFirst 2 rows of data/clean.csv\n"
    )
    assert "Last run: not recorded for its current outputs\n" in get_text(
        table["panel"]
    )
    # Something imported says from where, and something nothing accounts
    # for says how to fix it
    photo = panels["figures/photo.png"]["panel"][0]
    assert get_titles(photo)[0].startswith("Figure: Imported from")
    assert "https://example.com/photo.png" in json.dumps(photo)
    sketch = panels["figures/sketch.png"]["panel"][0]
    assert sketch["kind"] == "warning"
    assert get_titles(sketch) == [
        "Figure has incomplete provenance: origin not defined for "
        "figures/sketch.png"
    ]
    assert (
        "To fix figures/sketch.png: it's exported from something else"
        in get_text(sketch)
    )
    assert get_titles(panels["figures/gone.png"]["panel"][0]) == [
        "Figure missing"
    ]
    # So does the document showing them
    assert res["document"]["panel"][0]["kind"] == "warning"
    # Without them, it lists what it's made from, but not its own output
    text = "".join(
        line + "\n"
        for line in text.splitlines()
        if "sketch" not in line and "gone" not in line
    )
    res = get_panels(text, files)
    doc = res["document"]["panel"][0]
    doc_text = get_text(doc)
    assert get_titles(doc) == ["Document up to date"]
    assert "Rendered by: stage report, quarto\n" in doc_text
    assert "Last run" not in doc_text
    assert "Environment: _system, i.e., none\n" in doc_text
    assert "data/clean.csvclean✅ up to date\n" in doc_text
    assert "figures/plot.svgplot✅ up to date\n" in doc_text
    assert "Not checked: report.html, this document's own output" in doc_text
    assert "report.htmlreport" not in doc_text
    sections = {c.get("section") for c in doc["children"]}
    assert {"table", "graph"} <= sections
    graph = next(c for c in doc["children"] if c.get("section") == "graph")
    assert graph["type"] == "mermaid"
    assert '[["plot"]]' in graph["value"]
    assert '("figures/plot.svg"):::ok' in graph["value"]
    # An edited script makes what it made out of date, and what's made from
    # that wait on it, with even the document's own edits not counted
    stale = {"status": "stale", "modified_inputs": ["scripts/clean.py"]}
    res = get_panels(
        text,
        files,
        statuses={
            "clean": stale,
            "report": {**stale, "modified_inputs": ["report.qmd"]},
        },
    )
    assert get_titles(res["panels"]["figures/plot.svg"]["panel"][0]) == [
        "Figure out of date: waiting on data/clean.csv"
    ]
    plot_text = get_text(res["panels"]["figures/plot.svg"]["panel"])
    assert "data/clean.csvclean⚠️ out of date\n" in plot_text
    assert "To update: calkit run\n" in plot_text
    assert get_titles(res["panels"]["data/clean.csv"]["panel"][0]) == [
        "Table out of date: scripts/clean.py modified"
    ]
    doc = res["document"]["panel"][0]
    assert doc["kind"] == "danger"
    assert get_titles(doc) == ["Document out of date: 2 of 2 outputs"]
    graph = next(c for c in doc["children"] if c.get("section") == "graph")
    assert '("data/clean.csv"):::stale' in graph["value"]
    assert '("figures/plot.svg"):::waiting' in graph["value"]
    # As do an output edited by hand, a deleted input, and a stage that
    # always runs, which doesn't hold up what's made from it
    missing = {k: v for k, v in files.items() if k != "data/clean.csv"}
    cases: list[tuple[dict, dict, str]] = [
        (
            files,
            {"plot": {"status": "stale", "modified_outputs": ["figures"]}},
            "Figure out of date: modified outside pipeline",
        ),
        (
            missing,
            {
                "plot": {
                    "status": "stale",
                    "modified_inputs": ["data/clean.csv"],
                },
                "clean": {
                    "status": "stale",
                    "missing_outputs": ["data/clean.csv"],
                },
            },
            "Figure out of date: data/clean.csv missing",
        ),
        (files, {"clean": {"status": "always-run"}}, "Figure up to date"),
    ]
    for hashes, statuses, title in cases:
        res = get_panels(text, hashes, statuses=statuses)
        assert get_titles(res["panels"]["figures/plot.svg"]["panel"][0]) == [
            title
        ]
    # Raw data with no origin is a gap the document reports too
    ck_info["datasets"] = []
    res = get_panels(text, files)
    doc = res["document"]["panel"][0]
    assert doc["kind"] == "warning"
    assert get_titles(doc) == [
        "Document has incomplete provenance: origin not defined for "
        "data/raw.csv"
    ]
    assert get_titles(res["panels"]["data/clean.csv"]["panel"][0]) == [
        "Table has incomplete provenance: origin not defined for data/raw.csv"
    ]
    # A document no Quarto stage renders can name the stage that does
    doc = get_panels("::: ckprovenance\n:::\n", files, "index.md")["document"]
    assert get_titles(doc["panel"][0]) == [
        "Document has incomplete provenance: no stage renders it"
    ]
    doc = get_panels("::: ckprovenance\n:::\n", files, "index.md", "report")
    assert "Rendered by: stage report" in get_text(doc["document"]["panel"])
    # Written where the filter reads it, beside nothing else
    assert calkit.quarto.get_provenance_path("pub/report.qmd") == (
        ".calkit/local/provenance/pub/report.qmd.json"
    )


def test_stage_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def dvc(*args: str) -> str:
        return subprocess.check_output(
            [sys.executable, "-m", "dvc", *args], text=True, cwd=tmp_path
        )

    def get_statuses() -> dict[str, dict]:
        repo = calkit.dvc.get_dvc_repo(str(tmp_path))
        return {
            stage.addressing: calkit.quarto.get_stage_status(stage)
            for stage in repo.index.stages
        }

    def write_pipeline(make: dict, each_cmd: str) -> None:
        with open(tmp_path / "dvc.yaml", "w") as f:
            calkit.ryaml.dump(
                {
                    "stages": {
                        "make": {"cmd": "cp in.txt out.txt", **make},
                        "each": {
                            "matrix": {"n": ["x", "y"]},
                            "cmd": each_cmd,
                            "outs": ["${item.n}.txt"],
                        },
                    }
                },
                f,
            )

    monkeypatch.chdir(tmp_path)
    dvc("init", "--no-scm")
    (tmp_path / "in.txt").write_text("in\n")
    (tmp_path / "extra.txt").write_text("extra\n")
    make = {"deps": ["in.txt"], "outs": ["out.txt"]}
    each_cmd = "echo ${item.n} > ${item.n}.txt"
    write_pipeline(make, each_cmd)
    dvc("repro")
    assert {n: s["status"] for n, s in get_statuses().items()} == {
        "make": "up-to-date",
        "each@x": "up-to-date",
        "each@y": "up-to-date",
    }
    # It says what DVC does, for what's read or made being added or removed,
    # which DVC doesn't count for an output, and an iterated stage's command
    # changing, without the repo lock
    cases: list[tuple[dict, str, set[str], dict]] = [
        (
            {**make, "deps": ["in.txt", "extra.txt"]},
            each_cmd,
            {"make"},
            {"modified_inputs": ["extra.txt"]},
        ),
        (
            {**make, "outs": ["out.txt", "out2.txt"]},
            each_cmd,
            {"make"},
            {"missing_outputs": ["out2.txt"]},
        ),
        ({**make, "outs": []}, each_cmd, set(), {}),
        (
            make,
            "echo ${item.n}! > ${item.n}.txt",
            {"each@x", "each@y"},
            {"modified_command": True},
        ),
    ]
    for case_make, case_cmd, names, expected in cases:
        write_pipeline(case_make, case_cmd)
        stale = set(json.loads(dvc("status", "--json")))
        got = get_statuses()
        assert {n for n, s in got.items() if s["status"] == "stale"} == stale
        assert stale == names, (case_make, case_cmd)
        for name in names:
            assert {k: got[name][k] for k in expected} == expected
    # One that hasn't changed is up to date again
    write_pipeline(make, each_cmd)
    assert all(s["status"] == "up-to-date" for s in get_statuses().values())


def test_filter_problem(tmp_path: Path) -> None:
    listed = (
        "---\ntitle: T\nfilters:\n  - at: pre-ast\n    path: calkit\n---\n"
    )
    assert calkit.quarto.get_filter_problem(listed, "doc.qmd") is None
    # Not listed, or listed to run after Quarto numbers figures, says what
    # to add
    for text, match in [
        ("---\ntitle: T\n---\n", "need Calkit's filter listed,"),
        ("No front matter\n", "need Calkit's filter listed,"),
        ("---\nfilters: [calkit]\n---\n", "listed to run at pre-ast"),
    ]:
        problem = calkit.quarto.get_filter_problem(text, "doc.qmd")
        assert problem is not None and match in problem
        assert calkit.quarto.FILTER_CONFIG in problem
    # One listed for a format runs for that format
    html_only = (
        "---\nformat:\n  html+raw:\n    filters:\n"
        "      - {at: pre-ast, path: calkit}\n---\n"
    )
    for to, ok in [(None, True), ("html", True), ("pdf", False)]:
        problem = calkit.quarto.get_filter_problem(html_only, "doc.qmd", to=to)
        assert (problem is None) == ok, to
    # The Quarto project's config, or a folder's metadata, can list it
    (tmp_path / "pub" / "pages").mkdir(parents=True)
    (tmp_path / "pub" / "_quarto.yml").write_text(
        "project:\n  type: website\nformat:\n  html:\n    filters:\n"
        "      - {at: pre-ast, path: calkit}\n"
    )
    assert (
        calkit.quarto.get_filter_problem(
            "Text\n", "pub/pages/doc.qmd", wdir=str(tmp_path)
        )
        is None
    )
    (tmp_path / "pub" / "_quarto.yml").write_text(
        "project:\n  type: default\n"
    )
    assert calkit.quarto.get_filter_problem(
        "Text\n", "pub/pages/doc.qmd", wdir=str(tmp_path)
    )
    (tmp_path / "pub" / "pages" / "_metadata.yml").write_text(listed[4:-4])
    assert (
        calkit.quarto.get_filter_problem(
            "Text\n", "pub/pages/doc.qmd", wdir=str(tmp_path)
        )
        is None
    )


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs Quarto")
def test_provenance_filter(tmp_path: Path) -> None:
    def render(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "quarto", "render", "-e", "_system", *args],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

    subprocess.check_call(["calkit", "init"], cwd=tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "figures").mkdir()
    (tmp_path / "data" / "raw.csv").write_text("x,y\n1,2\n3,4\n")
    # With a byte order mark and something that isn't UTF-8
    (tmp_path / "data" / "bom.csv").write_bytes(b"\xef\xbb\xbfp,q\n\xff,2\n")
    (tmp_path / "scripts" / "clean.py").write_text(
        "import shutil\nshutil.copy('data/raw.csv', 'data/clean.csv')\n"
    )
    (tmp_path / "scripts" / "plot.py").write_text(
        "open('figures/plot.svg', 'w').write(\n"
        '    \'<svg xmlns="http://www.w3.org/2000/svg" width="10" '
        'height="10"/>\'\n)\n'
    )
    stage = {"kind": "python-script", "environment": "_system"}
    ck_info = {
        "requirements": ["quarto"],
        "datasets": [
            {"path": "data/raw.csv", "created_by": {"name": "Jo"}},
            {"path": "data/bom.csv", "created_by": {"name": "Jo"}},
        ],
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
                "report": {
                    "kind": "quarto",
                    "target_path": "report.qmd",
                    "environment": "_system",
                    "outputs": ["report.html"],
                },
            }
        },
    }
    with open(tmp_path / "calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    body = (
        '::: {.ckprovenance src="figures/plot.svg" #fig-plot width="50%"}\n'
        "The plot.\n:::\n\n"
        "See @fig-plot and @tbl-data.\n\n"
        "::: {.ckprovenance src=data/clean.csv #tbl-data}\nThe data.\n:::\n\n"
        "::: {.ckprovenance src=data/bom.csv #tbl-bom} :::\nBOM.\n:::\n\n"
        "::: {.ckprovenance graph=false}\n:::\n\n"
        "::: {.calkit-provenance}\n:::\n"
    )
    # Without the filter listed, it fails before rendering, saying what to
    # add
    (tmp_path / "report.qmd").write_text("---\ntitle: Report\n---\n\n" + body)
    res = render("report.qmd")
    assert res.returncode != 0
    assert calkit.quarto.FILTER_CONFIG in res.stdout + res.stderr
    (tmp_path / "report.qmd").write_text(
        "---\ntitle: Report\n" + calkit.quarto.FILTER_CONFIG + "---\n\n" + body
    )
    subprocess.check_call(["calkit", "run"], cwd=tmp_path)
    # What it shows is what it's made from
    with open(tmp_path / "dvc.yaml") as f:
        deps = calkit.ryaml.load(f)["stages"]["report"]["deps"]
    assert {"figures/plot.svg", "data/clean.csv"} <= set(deps)
    html = (tmp_path / "report.html").read_text()
    assert "Figure up to date" in html
    assert "Document up to date" in html
    assert "callout-note" in html
    res = render("report.qmd", "--to", "gfm", "--", "-o", "report.md")
    assert res.returncode == 0, res.stdout + res.stderr
    md = (tmp_path / "report.md").read_text().replace("\xa0", " ")
    # Numbered and cross-referenced by Quarto, so the filter ran first,
    # with non-breaking spaces as plain ones
    assert "Figure 1: The plot." in md
    assert "Table 1: The data." in md
    assert 'href="#fig-plot" class="quarto-xref">Figure 1' in md
    assert "| 1   | 2   |" in md
    assert "| p   | q   |" in md
    assert "Table 2: BOM." in md
    assert "Made by:** stage `plot`" in md
    assert "Not checked:** `report.html`" in md
    # A section turned off isn't there, nor is a misnamed div left silent
    assert "flowchart" not in md
    assert "Use `.ckprovenance` rather than `.calkit-provenance`" in md
    # An edited script makes what's made from it out of date
    with open(tmp_path / "scripts" / "clean.py", "a") as f:
        f.write("# Edited\n")
    res = render("report.qmd", "--to", "gfm", "--", "-o", "report.md")
    assert res.returncode == 0, res.stdout + res.stderr
    md = (tmp_path / "report.md").read_text().replace("\xa0", " ")
    assert "Figure out of date: waiting on data/clean.csv" in md
    assert "Table out of date: scripts/clean.py modified" in md
    assert "Document out of date: 2 of 2 outputs" in md
    # Rendered without Calkit after the document changed, it says so
    record_path = tmp_path / calkit.quarto.get_provenance_path("report.qmd")
    record = json.loads(record_path.read_text())
    assert (
        record["source_sha1"]
        == hashlib.sha1((tmp_path / "report.qmd").read_bytes()).hexdigest()
    )
    with open(tmp_path / "report.qmd", "a") as f:
        f.write("\nMore text.\n")
    subprocess.check_call(
        ["quarto", "render", "report.qmd", "--to", "gfm", "-o", "report.md"],
        cwd=tmp_path,
    )
    md = (tmp_path / "report.md").read_text()
    assert md.count("Document changed since panels recorded") == 4
    # With nothing recorded, it says so
    record_path.unlink()
    subprocess.check_call(
        ["quarto", "render", "report.qmd", "--to", "gfm", "-o", "report.md"],
        cwd=tmp_path,
    )
    md = (tmp_path / "report.md").read_text().replace("\xa0", " ")
    assert "Figure 1: The plot." in md
    assert 'href="#tbl-data" class="quarto-xref">Table 1' in md
    assert "Table 1: The data." in md
    assert md.count("No provenance recorded") == 4
