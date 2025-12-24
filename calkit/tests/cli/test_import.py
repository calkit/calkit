"""Tests for ``calkit.cli.import_``."""

import subprocess


def test_import_zenodo(tmp_dir, monkeypatch):
    subprocess.run(["calkit", "init"], check=True)
    # Temporarily disable dev mode so we can download a real record
    monkeypatch.setenv("CALKIT_USE_PROD_FOR_TESTS", "1")
    subprocess.run(
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
    # TODO: Test more about this
