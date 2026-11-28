"""Tests for ``tables``."""

import json
import os

import git
import pytest

import calkit
import calkit.tables

KERNELS = (
    "kernel,registers_baseline,registers_mod,occupancy_mod\n"
    "set_microphysics,255,153,18.55\n"
    "set_cloud_fraction,38,38,75.0\n"
    "copyto_by_slices,48,48,62.5\n"
)


def test_read_table(tmp_dir):
    with open("kernels.csv", "w") as f:
        f.write(KERNELS)
    table = calkit.tables.read_table("kernels.csv")
    assert table["columns"] == [
        "kernel",
        "registers_baseline",
        "registers_mod",
        "occupancy_mod",
    ]
    assert table["n_rows"] == 3
    assert table["rows"][0][0] == "set_microphysics"
    # Columns are selected in the order asked for, by name or glob, and
    # never repeated when two patterns cover the same one
    table = calkit.tables.read_table(
        "kernels.csv", columns=["*_mod", "kernel", "registers_mod"]
    )
    assert table["columns"] == ["registers_mod", "occupancy_mod", "kernel"]
    # A pattern that matches nothing says what the table does have
    with pytest.raises(ValueError, match="registers_baseline"):
        calkit.tables.read_table("kernels.csv", columns=["regs"])
    # Filters: numeric comparison, exact match, and substring
    table = calkit.tables.read_table(
        "kernels.csv", filters=["registers_baseline>100"]
    )
    assert [row[0] for row in table["rows"]] == ["set_microphysics"]
    assert table["n_rows_matching"] == 1
    assert table["n_rows"] == 3
    table = calkit.tables.read_table(
        "kernels.csv", filters=["kernel=set_cloud_fraction"]
    )
    assert len(table["rows"]) == 1
    table = calkit.tables.read_table("kernels.csv", filters=["kernel~MICRO"])
    assert [row[0] for row in table["rows"]] == ["set_microphysics"]
    table = calkit.tables.read_table(
        "kernels.csv", filters=["registers_mod<=48", "kernel~copyto"]
    )
    assert len(table["rows"]) == 1
    # A filter that can't be read, or names a column that isn't there, or
    # compares text with an operator only numbers have
    for bad in ["registers_mod", "regs>1", "kernel>1"]:
        with pytest.raises(ValueError):
            calkit.tables.read_table("kernels.csv", filters=[bad])
    # Row selection is 1-based and ranges can be open on either end
    table = calkit.tables.read_table("kernels.csv", rows="2-")
    assert [row[0] for row in table["rows"]] == [
        "set_cloud_fraction",
        "copyto_by_slices",
    ]
    table = calkit.tables.read_table("kernels.csv", rows="1,3")
    assert [row[0] for row in table["rows"]] == [
        "set_microphysics",
        "copyto_by_slices",
    ]
    assert calkit.tables.read_table("kernels.csv", head=2)["rows"] == table[
        "rows"
    ][:1] + [["set_cloud_fraction", "38", "38", "75.0"]]
    assert len(calkit.tables.read_table("kernels.csv", tail=1)["rows"]) == 1
    assert calkit.tables.read_table("kernels.csv", tail=0)["rows"] == []
    table = calkit.tables.read_table("kernels.csv", rows="-2")
    assert [row[0] for row in table["rows"]] == [
        "set_microphysics",
        "set_cloud_fraction",
    ]
    # A blank cell doesn't match a numeric filter rather than failing it
    with open("gaps.csv", "w") as f:
        f.write("kernel,speed\na,10\nb,\nc,2\n")
    table = calkit.tables.read_table("gaps.csv", filters=["speed>5"])
    assert [row[0] for row in table["rows"]] == ["a"]
    assert calkit.tables.read_columns("gaps.csv") == ["kernel", "speed"]
    # Tab-separated text is read the same way, and a short row is padded
    # rather than dropped
    with open("kernels.tsv", "w") as f:
        f.write("kernel\tregisters\nset_microphysics\t255\nshort\n")
    table = calkit.tables.read_table("kernels.tsv")
    assert table["rows"] == [["set_microphysics", "255"], ["short", ""]]
    # Contents can be given instead of a path, which is how a table is
    # read at a Git ref
    table = calkit.tables.read_table("kernels.csv", content=KERNELS.encode())
    assert table["n_rows"] == 3
    with pytest.raises(ValueError, match="'.nc' file"):
        calkit.tables.read_table("data.nc")


def test_list_tables(tmp_dir):
    git.Repo.init()
    os.makedirs("results", exist_ok=True)
    with open("results/kernels.csv", "w") as f:
        f.write(KERNELS)
    with open("results/summary.json", "w") as f:
        f.write("{}")
    with open("notes.txt", "w") as f:
        f.write("not a table\n")
    with open("results/case-a.csv", "w") as f:
        f.write("a,b\n1,2\n")
    ck_info = {
        "tables": [
            {
                "path": "results/kernels.csv",
                "title": "Kernel resources",
                "description": "Registers and occupancy per kernel.",
            }
        ],
        "pipeline": {
            "stages": {
                "export": {
                    "kind": "shell-command",
                    "command": "echo hi",
                    "outputs": ["results/kernels.csv"],
                },
                "other": {
                    "kind": "shell-command",
                    "command": "echo hi",
                    "outputs": ["results/missing.csv"],
                },
                "per-case": {
                    "kind": "shell-command",
                    "command": "echo {case}",
                    "iterate_over": [
                        {"arg_name": "case", "values": ["a", "b"]}
                    ],
                    "outputs": ["results/case-{case}.csv"],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    tables = {t["path"]: t for t in calkit.tables.list_tables()}
    # The declared one carries its metadata and isn't detected again, the
    # undeclared pipeline output is listed even though it isn't on disk,
    # and non-tabular files are left out
    assert tables["results/kernels.csv"]["title"] == "Kernel resources"
    assert tables["results/kernels.csv"]["detected"] is False
    assert tables["results/kernels.csv"]["stages"] == ["export"]
    assert tables["results/kernels.csv"]["exists"] is True
    assert tables["results/missing.csv"]["exists"] is False
    assert "results/summary.json" not in tables
    assert "notes.txt" not in tables
    # An iterated stage's output is matched to what each iteration writes
    # rather than listed as its template
    assert tables["results/case-a.csv"]["stages"] == ["per-case"]
    assert not any("{" in path for path in tables)
    declared = calkit.tables.list_tables(declared_only=True)
    assert [t["path"] for t in declared] == ["results/kernels.csv"]
    # A tabular file that isn't declared anywhere is still detected
    with open("results/extra.csv", "w") as f:
        f.write("a,b\n1,2\n")
    tables = {t["path"]: t for t in calkit.tables.list_tables()}
    assert tables["results/extra.csv"]["detected"] is True
    assert "stages" not in tables["results/extra.csv"]
    # A table a notebook's cell is marked to make is listed in any format
    ck_info["pipeline"]["stages"]["fit"] = {
        "kind": "jupyter-notebook",
        "notebook_path": "fit.ipynb",
        "environment": "py",
        "cell_outputs": [
            {
                "kind": "table",
                "cell_id": "a",
                "variable_name": "df",
                "output_path": "tables/k.tex",
            }
        ],
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    tables = {t["path"]: t for t in calkit.tables.list_tables()}
    assert tables["tables/k.tex"]["stages"] == ["fit"]
    assert tables["tables/k.tex"]["exists"] is False
    assert "tables/k.tex" not in [
        t["path"] for t in calkit.tables.list_tables(declared_only=True)
    ]


def test_write_table(tmp_dir):
    table = {
        "columns": ["T (°C)", "k_obs", "note"],
        "index": None,
        "index_name": None,
        "data": [
            [25, 0.030912, "50% & up"],
            [35, -0.0616, None],
            [45, 1.5e-05, [1, 2]],
        ],
    }
    calkit.tables.write_table("tables/rates.tex", table, ".3f")
    with open("tables/rates.tex", encoding="utf-8") as f:
        tex = f.read()
    # Numbers right, text left, with booktabs' rules or plain lines
    assert r"\begin{tabular}{rrl}" in tex
    assert r"\providecommand{\toprule}{\hline}" in tex
    assert r"T (°C) & k\_obs & note \\" in tex
    assert r"25 & 0.031 & 50\% \& up \\" in tex
    assert r"35 & $-$0.062 &  \\" in tex
    assert r"45 & 0.000 & 1, 2 \\" in tex
    calkit.tables.write_table("rates.csv", table)
    with open("rates.csv", encoding="utf-8") as f:
        assert f.read().splitlines() == [
            "T (°C),k_obs,note",
            "25,0.030912,50% & up",
            "35,-0.0616,",
            '45,1.5e-05,"1, 2"',
        ]
    calkit.tables.write_table(
        "full.csv", {"columns": ["k"], "data": [[1 / 3]]}
    )
    with open("full.csv", encoding="utf-8") as f:
        assert f.read().splitlines()[1] == "0.3333333333333333"
    calkit.tables.write_table("rates.md", table)
    with open("rates.md", encoding="utf-8") as f:
        assert f.read().splitlines()[:3] == [
            "| T (°C) | k_obs | note |",
            "|---|---|---|",
            "| 25 | 0.030912 | 50% & up |",
        ]
    # An index is the first column, named for the index
    indexed = table | {"index": ["a", "b", "c"], "index_name": "run"}
    calkit.tables.write_table("rates.json", indexed)
    with open("rates.json", encoding="utf-8") as f:
        records = json.load(f)
    assert records[0] == {
        "run": "a",
        "T (°C)": 25,
        "k_obs": 0.030912,
        "note": "50% & up",
    }
    calkit.tables.write_table("indexed.tex", indexed)
    with open("indexed.tex", encoding="utf-8") as f:
        assert r"run & T (°C) & k\_obs & note \\" in f.read()
    # Formatted numbers are escaped too
    calkit.tables.write_table(
        "pct.tex", {"columns": ["f"], "data": [[0.123]]}, ".1%"
    )
    calkit.tables.write_table(
        "big.tex", {"columns": ["n"], "data": [[-1234.5]]}, "_.1f"
    )
    with open("pct.tex", encoding="utf-8") as f:
        assert r"12.3\% \\" in f.read()
    with open("big.tex", encoding="utf-8") as f:
        assert r"$-$1\_234.5 \\" in f.read()
    with pytest.raises(ValueError, match="'.xlsx'"):
        calkit.tables.write_table("rates.xlsx", table)


def test_get_row_counts(tmp_dir):
    participants = ["id,site,arm,age"] + [
        f"{s}-{i},{s},{'ab'[i % 2]},{60 + i}" for s in "ABD" for i in range(4)
    ]
    with open("participants.csv", "w") as f:
        f.write("\n".join(participants) + "\n")
    # Long, so with more rows than the output, and no last newline
    with open("sessions.tsv", "w") as f:
        f.write("id\tweek\n" + "\n".join(f"A-{i}\t0" for i in range(30)))
    # Site D's rows lost, as by unpadded IDs failing to merge
    with open("analysis.csv", "w") as f:
        f.write("\n".join(participants[:9]) + "\n")
    with open("empty.csv", "w") as f:
        f.write("id,site\n")
    with open("script.py", "w") as f:
        f.write("print('hi')\n")
    os.makedirs("data")
    # Lines are counted, not parsed, a header less
    assert calkit.tables.count_rows("participants.csv") == 12
    assert calkit.tables.count_rows("sessions.tsv") == 30
    assert calkit.tables.count_rows("empty.csv") == 0
    for path in ("script.py", "data", "missing.csv"):
        assert calkit.tables.count_rows(path) is None
    assert calkit.tables.count_rows("participants.csv", max_bytes=10) is None
    # Only repeated text values are taken for groups, not IDs or numbers
    assert calkit.tables.count_groups("participants.csv") == {
        "site": {"A": 4, "B": 4, "D": 4},
        "arm": {"a": 6, "b": 6},
    }
    assert calkit.tables.count_groups("participants.csv", max_groups=2) == {
        "arm": {"a": 6, "b": 6}
    }
    assert calkit.tables.count_groups("participants.csv", max_bytes=10) == {}
    counts = calkit.tables.get_row_counts(
        ["participants.csv", "sessions.tsv", "script.py"], ["analysis.csv"]
    )
    assert counts == {
        "inputs": {"participants.csv": 12, "sessions.tsv": 30},
        "outputs": {"analysis.csv": 8},
        "lost_groups": {"analysis.csv": {"site": {"D": 4}}},
    }
    assert calkit.tables.get_row_counts_text("prepare-data", counts) == (
        "prepare-data: participants.csv 12 rows, sessions.tsv 30 rows -> "
        "analysis.csv 8 rows (4 fewer than participants.csv, 33%; "
        "site D: 4 -> 0 rows)"
    )
    # More rows than the smallest input, e.g., a reshape to long, isn't noted
    counts = calkit.tables.get_row_counts(["analysis.csv"], ["sessions.tsv"])
    assert calkit.tables.get_row_counts_text("s", counts) == (
        "s: analysis.csv 8 rows -> sessions.tsv 30 rows"
    )
    # Nor is anything without an input table to compare with
    counts = calkit.tables.get_row_counts(["script.py"], ["empty.csv"])
    assert counts == {"inputs": {}, "outputs": {"empty.csv": 0}}
    assert calkit.tables.get_row_counts_text("s", counts) == (
        "s: empty.csv 0 rows"
    )
    # Parquet is counted from its metadata
    pq = pytest.importorskip("pyarrow.parquet")
    import pyarrow

    pq.write_table(pyarrow.table({"x": [1, 2, 3]}), "x.parquet")
    assert calkit.tables.count_rows("x.parquet") == 3
