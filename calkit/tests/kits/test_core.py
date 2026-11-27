"""Tests for ``calkit.kits.core``."""

import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import git
import pytest

import calkit
import calkit.kits
from calkit.kits.core import MANIFEST_NAME, PROJECT_DIR, write_zip


def test_build_read_expand(kit_project, tmp_path):
    # Project state that shouldn't travel with a kit
    os.makedirs(".calkit/overleaf")
    with open(".calkit/overleaf/info.json", "w") as f:
        f.write('{"secret": true}')
    subprocess.check_call(["git", "add", "-f", ".calkit/overleaf"])
    subprocess.check_call(["git", "commit", "-qm", "Overleaf"])
    commit_sha = git.Repo().head.commit.hexsha
    # Every format round-trips to the original bytes, and the artifact is
    # the output the pipeline recorded
    for path in [
        "figures/fig.png",
        "figures/fig.pdf",
        "figures/fig.svg",
        "figures/page.html",
    ]:
        with open(path, "rb") as f:
            original = f.read()
        out_path = str(tmp_path / os.path.basename(path))
        manifest = calkit.kits.write_copy(path, out_path, up_to_date=True)
        kit = calkit.kits.read(out_path)
        assert kit is not None
        assert kit.artifact == original
        assert kit.artifact_unchanged
        assert kit.matches_pipeline is True
        assert kit.manifest == manifest
    # The manifest says where the kit came from, without credentials
    assert manifest.artifact.path == "figures/page.html"
    assert manifest.artifact.stage == "make"
    assert manifest.source.name == "kit-test"
    assert manifest.source.commit_sha == commit_sha
    assert manifest.source.git_remotes == {
        "origin": "https://github.com/someone/kit-test.git"
    }
    assert manifest.source.uncommitted_paths == []
    files = {f.path: f for f in manifest.files}
    assert files["scripts/make.py"].included
    assert files["scripts/make.py"].storage == "git"
    assert files["data/raw.csv"].included
    assert files["data/raw.csv"].storage == "dvc"
    assert files["data/raw.csv"].md5
    assert "data/raw.csv.dvc" in files
    assert ".calkit/overleaf/info.json" not in files
    assert "figures/page.html" not in files
    with zipfile.ZipFile(io.BytesIO(kit.kit)) as z:
        names = z.namelist()
        runs = json.loads(z.read(PROJECT_DIR + ".calkit/stage-runs.json"))
    assert names[0] == MANIFEST_NAME
    assert PROJECT_DIR + "scripts/make.py" in names
    assert "machine_id" not in runs["make"]["system"]
    # The same project state makes the same kit
    kit_1, _ = calkit.kits.build("figures/fig.png", up_to_date=True)
    kit_2, _ = calkit.kits.build("figures/fig.png", up_to_date=True)
    assert kit_1 == kit_2
    # Data is left out once the kit is full, or when asked, with its hash
    # kept so a copy can pull it
    for kwargs in [{"max_size": 1000}, {"include_data": False}]:
        _, manifest = calkit.kits.build(
            "figures/fig.png", up_to_date=True, **kwargs
        )
        raw = next(f for f in manifest.files if f.path == "data/raw.csv")
        assert not raw.included
        assert raw.sha256 is None
        assert raw.md5 == files["data/raw.csv"].md5
    # Embedding again replaces the kit, rather than adding another
    png_path = str(tmp_path / "fig.png")
    with open(png_path, "rb") as f:
        data = f.read()
    data = calkit.kits.embed(data, png_path, kit_1)
    assert data.count(calkit.kits.png.CHUNK_TYPE) == 1
    # A changed artifact, here its width, no longer matches its kit
    with open("figures/fig.png", "rb") as f:
        original = f.read()
    tampered_path = str(tmp_path / "tampered.png")
    with open(tampered_path, "wb") as f:
        f.write(data[:16] + b"\x00\x00\x01\x00" + data[20:])
    tampered_kit = calkit.kits.read(tampered_path)
    assert tampered_kit is not None
    assert not tampered_kit.artifact_unchanged
    # Files without a kit, or that kits can't go in, read as having none
    assert calkit.kits.read("figures/fig.png") is None
    assert calkit.kits.read("data/raw.csv") is None
    with pytest.raises(ValueError, match="No pipeline stage"):
        calkit.kits.build("scripts/make.py", up_to_date=True)
    # Expanding makes a committed project that's up to date, linked to the
    # original, with what DVC tracks in its cache
    dest_dir = tmp_path / "expanded"
    calkit.kits.expand(png_path, str(dest_dir))
    with open(dest_dir / "figures/fig.png", "rb") as f:
        assert f.read() == original
    assert (dest_dir / "data/raw.csv").is_file()
    assert not (dest_dir / ".calkit/overleaf").exists()
    repo = git.Repo(dest_dir)
    assert not repo.is_dirty(untracked_files=True)
    assert "data/raw.csv" not in repo.git.ls_files().splitlines()
    assert repo.remote("upstream").url == (
        "https://github.com/someone/kit-test.git"
    )
    assert commit_sha[:7] in repo.head.commit.message
    status = subprocess.check_output(
        [sys.executable, "-m", "dvc", "status", "--json"], cwd=dest_dir
    )
    assert json.loads(status) == {}
    with pytest.raises(ValueError, match="isn't empty"):
        calkit.kits.expand(png_path, str(dest_dir))
    # Paths outside the project are refused
    manifest_json = kit.manifest.model_dump_json().encode()
    evil_kit = write_zip(
        {
            MANIFEST_NAME: (manifest_json, False),
            PROJECT_DIR + "../evil.txt": (b"evil", False),
        }
    )
    with open("figures/page.html", "rb") as f:
        evil = calkit.kits.html.embed(f.read(), evil_kit)
    evil_path = str(tmp_path / "evil.html")
    with open(evil_path, "wb") as f:
        f.write(evil)
    with pytest.raises(ValueError, match="outside the project"):
        calkit.kits.expand(evil_path, str(tmp_path / "evil"))
    assert not (tmp_path / "evil.txt").exists()


def test_generate_schema_json():
    schema = json.loads(calkit.kits.generate_schema_json())
    assert schema["$id"] == calkit.kits.SCHEMA_URL
    assert "artifact" in schema["required"]
    # The checked-in copy is what gets published
    repo_root = Path(__file__).parents[3]
    fpath = repo_root / calkit.kits.SCHEMA_REPO_PATH
    with open(fpath, encoding="utf-8") as f:
        assert f.read() == calkit.kits.generate_schema_json(), (
            f"{calkit.kits.SCHEMA_REPO_PATH} is out of date; regenerate it "
            "with 'make schema'"
        )
