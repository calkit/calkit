"""Tests for ``calkit.cli.import_``."""

import subprocess


def test_import_zenodo(tmp_dir):
    subprocess.run(["calkit", "init"], check=True)
    result = subprocess.run(
        [
            "calkit",
            "import",
            "zenodo",
            "https://doi.org/10.5281/zenodo.18038227",
            "data/imported",
            "--kind",
            "dataset",
        ],
        check=True,
    )
    assert result.returncode == 0
    # TODO: Test more about this
