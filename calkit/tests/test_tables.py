"""Tests for ``tables``."""

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
    declared = calkit.tables.list_tables(declared_only=True)
    assert [t["path"] for t in declared] == ["results/kernels.csv"]
    # A tabular file that isn't declared anywhere is still detected
    with open("results/extra.csv", "w") as f:
        f.write("a,b\n1,2\n")
    tables = {t["path"]: t for t in calkit.tables.list_tables()}
    assert tables["results/extra.csv"]["detected"] is True
    assert "stages" not in tables["results/extra.csv"]
