"""Tests for ``calkit.kits``."""

import base64
import io
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import git
import pypdfium2 as pdfium
import pytest
from PIL import Image

import calkit
import calkit.kits
from calkit.kits import MANIFEST_NAME, PROJECT_DIR, write_zip


def test_embed_extract():
    kit = b"PK\x03\x04 " + bytes(range(256)) * 4
    # PNG: a chunk before IEND that image readers skip
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, format="PNG")
    png = buf.getvalue()
    assert calkit.kits.extract_png(png) is None
    data = calkit.kits.embed_png(png, kit)
    assert data.endswith(png[-12:])
    assert Image.open(io.BytesIO(data)).size == (4, 4)
    assert calkit.kits.extract_png(data) == (kit, png)
    pos = data.index(calkit.kits.PNG_CHUNK_TYPE) + 4
    with pytest.raises(ValueError, match="corrupt"):
        calkit.kits.extract_png(data[:pos] + b"X" + data[pos + 1 :])
    with pytest.raises(ValueError, match="Not a PNG"):
        calkit.kits.embed_png(b"GIF89a", kit)
    with pytest.raises(ValueError, match="IEND"):
        calkit.kits.embed_png(png[:-12], kit)
    # PDF: an attachment appended, so the original is a prefix
    doc = pdfium.PdfDocument.new()
    doc.new_page(100, 100)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    pdf = buf.getvalue()
    assert calkit.kits.extract_pdf(pdf) is None
    manifest = {"artifact": {"size": len(pdf)}}
    pdf_kit = write_zip(
        {MANIFEST_NAME: (json.dumps(manifest).encode(), False)}
    )
    data = calkit.kits.embed_pdf(pdf, pdf_kit)
    assert data.startswith(pdf)
    doc = pdfium.PdfDocument(data)
    assert len(doc) == 1
    assert doc.get_attachment(0).get_name() == "calkit.zip"
    doc.close()
    assert calkit.kits.extract_pdf(data) == (pdf_kit, pdf)
    # HTML: wrapped base64 before the closing body tag, in any case, with a
    # comment saying what it is
    html = b"<!DOCTYPE html><html><body><p>Hi</p></BODY></html>\n"
    assert calkit.kits.extract_markup(html, "html") is None
    data = calkit.kits.embed_markup(html, kit, "html")
    assert data.index(calkit.kits.MARKUP_COMMENT) < data.index(b"</BODY>")
    assert base64.encodebytes(kit).splitlines()[0] in data
    assert calkit.kits.extract_markup(data, "html") == (kit, html)
    data = calkit.kits.embed_markup(b"<p>Hi</p>", kit, "html")
    assert data.startswith(b"<p>Hi</p><!-- Calkit")
    assert calkit.kits.extract_markup(data, "html") == (kit, b"<p>Hi</p>")
    # SVG: still well-formed, with the calkit in a metadata element
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>\n'
    assert calkit.kits.extract_markup(svg, "svg") is None
    data = calkit.kits.embed_markup(svg, kit, "svg")
    root = ET.fromstring(data)
    assert root.find("{http://www.w3.org/2000/svg}metadata") is not None
    assert calkit.kits.extract_markup(data, "svg") == (kit, svg)
    with pytest.raises(ValueError, match="</svg>"):
        calkit.kits.embed_markup(b"<svg>", kit, "svg")
    # Formats come from contents, and extensions for text
    assert calkit.kits.get_format(png, "fig.bin") == "png"
    assert calkit.kits.get_format(pdf, "paper") == "pdf"
    assert calkit.kits.get_format(b"<p>Hi</p>", "page.htm") == "html"
    with pytest.raises(ValueError, match="supported types"):
        calkit.kits.get_format(b"x,y\n", "data.csv")


def test_build_read_expand(kit_project, tmp_path):
    # Project state that shouldn't travel with a calkit
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
    # The manifest says where the calkit came from, without credentials, and
    # where to learn more
    assert manifest.schema_url == calkit.kits.SCHEMA_URL
    assert manifest.artifact.path == "figures/page.html"
    assert manifest.artifact.stage == "make"
    assert manifest.source.name == "kit-test"
    assert manifest.source.commit_sha == commit_sha
    assert manifest.source.git_remotes == {
        "origin": "https://github.com/someone/kit-test.git"
    }
    assert manifest.source.uncommitted_paths == []
    assert [g.path for g in manifest.provenance_gaps] == ["data/raw.csv"]
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
        manifest_json = json.loads(z.read(MANIFEST_NAME))
        readme = z.read(calkit.kits.README_NAME).decode()
        runs = json.loads(z.read(PROJECT_DIR + ".calkit/stage-runs.json"))
    assert names[:2] == [MANIFEST_NAME, calkit.kits.README_NAME]
    assert manifest_json["$schema"] == calkit.kits.SCHEMA_URL
    assert f"at commit {commit_sha}" in readme
    assert "calkit kit run page.html" in readme
    assert calkit.kits.DOCS_URL in readme
    assert PROJECT_DIR + "scripts/make.py" in names
    assert "machine_id" not in runs["make"]["system"]
    # The same project state makes the same calkit
    kit_1, _ = calkit.kits.build("figures/fig.png", up_to_date=True)
    kit_2, _ = calkit.kits.build("figures/fig.png", up_to_date=True)
    assert kit_1 == kit_2
    # Data is left out once the calkit is full, or when asked, with its hash
    # kept so a copy can pull it
    for kwargs in [{"max_size": 1000}, {"include_data": False}]:
        _, manifest = calkit.kits.build(
            "figures/fig.png", up_to_date=True, **kwargs
        )
        raw = next(f for f in manifest.files if f.path == "data/raw.csv")
        assert not raw.included
        assert raw.sha256 is None
        assert raw.md5 == files["data/raw.csv"].md5
    # Embedding again replaces the calkit, rather than adding another
    png_path = str(tmp_path / "fig.png")
    with open(png_path, "rb") as f:
        data = f.read()
    data = calkit.kits.embed(data, png_path, kit_1)
    assert data.count(calkit.kits.PNG_CHUNK_TYPE) == 1
    # A changed artifact, here its width, no longer matches its calkit
    with open("figures/fig.png", "rb") as f:
        original = f.read()
    tampered_path = str(tmp_path / "tampered.png")
    with open(tampered_path, "wb") as f:
        f.write(data[:16] + b"\x00\x00\x01\x00" + data[20:])
    tampered_kit = calkit.kits.read(tampered_path)
    assert tampered_kit is not None
    assert not tampered_kit.artifact_unchanged
    # Files without a calkit, or that one can't go in, read as having none
    assert calkit.kits.read("figures/fig.png") is None
    assert calkit.kits.read("data/raw.csv") is None
    with pytest.raises(ValueError, match="No pipeline stage"):
        calkit.kits.build("scripts/make.py", up_to_date=True)
    # Expanding makes a committed project that's up to date, linked to the
    # original, with what DVC tracks in its cache
    dest_dir = tmp_path / "expanded"
    kit = calkit.kits.expand(png_path, str(dest_dir))
    with open(dest_dir / "figures/fig.png", "rb") as f:
        assert f.read() == original
    assert (dest_dir / "data/raw.csv").is_file()
    assert not (dest_dir / ".calkit/overleaf").exists()
    assert calkit.kits.get_missing_inputs(kit, str(dest_dir)) == []
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
    # Inputs left out are missing until pulled, but outputs aren't inputs
    small_path = str(tmp_path / "small.png")
    calkit.kits.write_copy(
        "figures/fig.png", small_path, up_to_date=True, max_size=1000
    )
    small_kit = calkit.kits.expand(small_path, str(tmp_path / "small"))
    missing = calkit.kits.get_missing_inputs(
        small_kit, str(tmp_path / "small")
    )
    assert missing == ["data/raw.csv"]
    # Paths outside the project are refused
    manifest_json = kit.manifest.model_dump_json(by_alias=True).encode()
    evil_kit = write_zip(
        {
            MANIFEST_NAME: (manifest_json, False),
            PROJECT_DIR + "../evil.txt": (b"evil", False),
        }
    )
    with open("figures/page.html", "rb") as f:
        evil = calkit.kits.embed_markup(f.read(), evil_kit, "html")
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
    assert "$schema" in schema["properties"]
    # The checked-in copy is what gets published
    fpath = Path(__file__).parents[2] / calkit.kits.SCHEMA_REPO_PATH
    with open(fpath, encoding="utf-8") as f:
        assert f.read() == calkit.kits.generate_schema_json(), (
            f"{calkit.kits.SCHEMA_REPO_PATH} is out of date; regenerate it "
            "with 'make schema'"
        )
