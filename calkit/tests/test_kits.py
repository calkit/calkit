"""Tests for ``calkit.kits``."""

import base64
import hashlib
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
import calkit.hub
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
    pdf_manifest = calkit.kits.Manifest(
        created_with="test",
        artifact=calkit.kits.KitArtifact(
            path="paper.pdf", size=len(pdf), sha256="0" * 64, stage="paper"
        ),
        source=calkit.kits.KitSource(up_to_date=True),
        files=[],
    )
    pdf_kit = write_zip(
        {
            MANIFEST_NAME: (
                pdf_manifest.model_dump_json(by_alias=True).encode(),
                False,
            )
        }
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


def test_build_read_unbundle(kit_project, tmp_path):
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
        _, manifest = calkit.kits.write_copy(path, out_path, up_to_date=True)
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
    hub_project_url = (
        calkit.hub.get_hub_url().rstrip("/") + "/someone/kit-test"
    )
    assert manifest.source.hub_url == hub_project_url
    assert calkit.kits.get_hub_file_url(manifest) == (
        f"{hub_project_url}/files?path=figures%2Fpage.html&ref={commit_sha}"
    )
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
    # Unbundling makes a committed project that's up to date, linked to the
    # original, with what DVC tracks in its cache
    dest_dir = tmp_path / "unbundled"
    kit = calkit.kits.unbundle(png_path, str(dest_dir))
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
        calkit.kits.unbundle(png_path, str(dest_dir))
    # Inputs left out are missing until pulled, but outputs aren't inputs
    small_path = str(tmp_path / "small.png")
    calkit.kits.write_copy(
        "figures/fig.png", small_path, up_to_date=True, max_size=1000
    )
    small_kit = calkit.kits.unbundle(small_path, str(tmp_path / "small"))
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
    with pytest.raises(ValueError, match="unsafe path"):
        calkit.kits.unbundle(evil_path, str(tmp_path / "evil"))
    assert not (tmp_path / "evil.txt").exists()
    # Environment specs Calkit keeps in .calkit go along, and data kept in
    # Git obeys the size limit and leaving out data, as data in DVC does
    os.makedirs(".calkit/envs/py")
    with open(".calkit/envs/py/pyproject.toml", "w") as f:
        f.write('[project]\nname = "py"\nversion = "0"\n')
    with open(".calkit/envs/py/uv.lock", "w") as f:
        f.write("version = 1\n")
    with open("data/params.csv", "w") as f:
        f.write("a,b\n1,2\n")
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "py": {"kind": "uv", "path": ".calkit/envs/py/pyproject.toml"}
    }
    ck_info["pipeline"]["stages"]["make"]["environment"] = "py"
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(
        ["git", "add", "calkit.yaml", ".calkit/envs", "data/params.csv"]
    )
    subprocess.check_call(["git", "commit", "-qm", "Add env and params"])
    with open("dvc.yaml") as f:
        dvc_yaml = calkit.ryaml.load(f)
    dvc_yaml["stages"]["make"]["deps"].append("data/params.csv")
    with open("dvc.yaml", "w") as f:
        calkit.ryaml.dump(dvc_yaml, f)
    with open("dvc.lock") as f:
        lock = calkit.ryaml.load(f)
    lock["stages"]["make"]["deps"].append(
        {
            "path": "data/params.csv",
            "hash": "md5",
            "md5": "0" * 32,
            "size": 8,
        }
    )
    with open("dvc.lock", "w") as f:
        calkit.ryaml.dump(lock, f)
    _, manifest = calkit.kits.build(
        "figures/fig.png", up_to_date=True, include_data=False
    )
    files = {f.path: f for f in manifest.files}
    assert files[".calkit/envs/py/pyproject.toml"].included
    assert files[".calkit/envs/py/uv.lock"].included
    assert not files["data/params.csv"].included
    _, manifest = calkit.kits.build("figures/fig.png", up_to_date=True)
    assert {f.path: f for f in manifest.files}["data/params.csv"].included


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


def test_copy_to_clipboard(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("input")))

    monkeypatch.setattr("calkit.kits.subprocess.run", fake_run)
    path = str(tmp_path / "it's.png")
    # As a file, not its pixels, on each platform
    calkit.kits.copy_to_clipboard(path, platform="darwin")
    assert calls[-1][0][:3] == ["osascript", "-l", "JavaScript"]
    assert calls[-1][0][-1] == path
    assert "fileURLWithPath" in calls[-1][0][-2]
    calkit.kits.copy_to_clipboard(path, platform="win32")
    assert (
        calls[-1][0][-1]
        == f"Set-Clipboard -LiteralPath '{path.replace(chr(39), chr(39) * 2)}'"
    )
    monkeypatch.setattr("calkit.kits.shutil.which", lambda cmd: cmd == "xclip")
    calkit.kits.copy_to_clipboard(path, platform="linux")
    assert calls[-1][0][0] == "xclip"
    assert calls[-1][1] == Path(path).as_uri().encode()
    monkeypatch.setattr("calkit.kits.shutil.which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="wl-copy or xclip"):
        calkit.kits.copy_to_clipboard(path, platform="linux")


def test_untrusted_calkits(tmp_path):
    import time

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    png = buf.getvalue()

    def make_manifest(files: dict[str, bytes], **kwargs) -> dict:
        manifest = calkit.kits.Manifest(
            created_with="test",
            artifact=calkit.kits.KitArtifact(
                path="fig.png",
                size=len(png),
                sha256=hashlib.sha256(png).hexdigest(),
                stage="plot",
            ),
            source=calkit.kits.KitSource(name="../../evil", up_to_date=True),
            files=[
                calkit.kits.KitFile(
                    path=p,
                    size=len(c),
                    storage="git",
                    included=True,
                    sha256=hashlib.sha256(c).hexdigest(),
                )
                for p, c in files.items()
            ],
        )
        return manifest.model_dump(by_alias=True) | kwargs

    def write_png(
        files: dict[str, bytes],
        manifest: dict | None = None,
        name: str = "fig.png",
    ) -> str:
        entries = {
            MANIFEST_NAME: (
                json.dumps(manifest or make_manifest(files)).encode(),
                False,
            )
        }
        for p, c in files.items():
            entries[PROJECT_DIR + p] = (c, False)
        path = str(tmp_path / name)
        with open(path, "wb") as f:
            f.write(calkit.kits.embed_png(png, write_zip(entries)))
        return path

    # Git internals, e.g., hooks or config that run commands, and DVC local
    # config in any case are refused before anything is written
    for evil_path in [
        ".git/hooks/pre-commit",
        "sub/.GIT/config",
        "/etc/x",
        ".DVC/config.local",
        ".dvc/Config.Local",
    ]:
        files = {"run.py": b"print(1)\n", evil_path: b"#!/bin/sh\ntouch x\n"}
        dest = tmp_path / "dest"
        with pytest.raises(calkit.kits.KitError, match="unsafe path"):
            calkit.kits.unbundle(write_png(files), str(dest))
        assert not dest.exists()
    # Disallowed .dvc/config settings and unsafe Git remotes are refused
    for bad_cfg in [
        b"[cache]\n    dir = /tmp\n",
        b"[core]\n    site_cache_dir = /tmp\n",
        b"['remote \"x\"']\n    url = s3://b\n    endpointurl = http://evil\n",
    ]:
        dest = tmp_path / "dest-cfg"
        with pytest.raises(calkit.kits.KitError, match="disallowed settings"):
            calkit.kits.unbundle(
                write_png({".dvc/config": bad_cfg}), str(dest)
            )
        assert not dest.exists()
    for bad_remotes, match in [
        ({"bad name": "https://example.com/a.git"}, "unsafe remote name"),
        ({"origin": "--upload-pack=sh"}, "unsafe remote URL"),
        ({"origin": "ext::sh -c id"}, "unsafe remote URL"),
    ]:
        bad_manifest = make_manifest({"run.py": b"print(1)\n"})
        bad_manifest["source"]["git_remotes"] = bad_remotes
        dest = tmp_path / "dest-remote"
        with pytest.raises(calkit.kits.KitError, match=match):
            calkit.kits.unbundle(
                write_png({"run.py": b"print(1)\n"}, bad_manifest), str(dest)
            )
        assert not dest.exists()
    # Non-HTTP(S) hub URLs aren't opened
    bad_hub = calkit.kits.Manifest.model_validate(
        make_manifest({})
        | {"source": {"up_to_date": True, "hub_url": "file:///etc/passwd"}}
    )
    assert calkit.kits.get_hub_file_url(bad_hub) is None
    # So are files the manifest doesn't list, or that don't match it, or
    # that it lists but are missing
    files = {"run.py": b"print(1)\n"}
    manifest = make_manifest(files)
    extra = {**files, "extra.py": b"print(2)\n"}
    for path, match in [
        (write_png(extra, manifest, "a.png"), "doesn't match"),
        (
            write_png({"run.py": b"print(2)\n"}, manifest, "b.png"),
            "doesn't match",
        ),
        (write_png({}, manifest, "c.png"), "missing files"),
    ]:
        with pytest.raises(calkit.kits.KitError, match=match):
            calkit.kits.unbundle(path, str(tmp_path / "dest"))
    # A valid one unbundles, without its name choosing where
    good = write_png(files)
    calkit.kits.unbundle(good, str(tmp_path / "good"))
    assert (tmp_path / "good/run.py").read_bytes() == b"print(1)\n"
    # A newer format, a missing manifest, or a chunk that isn't a ZIP can't
    # be read, but a broken PNG just has no calkit
    newer = write_png(files, make_manifest(files, kit_version=2))
    with pytest.raises(calkit.kits.KitError, match="upgrade Calkit"):
        calkit.kits.read(newer)
    not_zip = tmp_path / "not-zip.png"
    not_zip.write_bytes(calkit.kits.embed_png(png, b"not a zip"))
    with pytest.raises(calkit.kits.KitError, match="valid ZIP"):
        calkit.kits.read(str(not_zip))
    no_manifest = tmp_path / "no-manifest.png"
    no_manifest.write_bytes(
        calkit.kits.embed_png(png, write_zip({"x": (b"x", False)}))
    )
    with pytest.raises(calkit.kits.KitError, match="no calkit-kit.json"):
        calkit.kits.read(str(no_manifest))
    bad_json = tmp_path / "bad-json.png"
    bad_json.write_bytes(
        calkit.kits.embed_png(
            png, write_zip({MANIFEST_NAME: (b"{bad", False)})
        )
    )
    with pytest.raises(calkit.kits.KitError, match="valid JSON"):
        calkit.kits.read(str(bad_json))
    truncated = tmp_path / "truncated.png"
    truncated.write_bytes(png[:20])
    assert calkit.kits.read(str(truncated)) is None
    # Many opening tags without a closing one don't make finding one slow
    open_tag = calkit.kits.MARKUP_BLOCKS["svg"][0]
    hostile = b"<svg>" + open_tag * 20_000 + b"</svg>"
    start = time.perf_counter()
    assert calkit.kits.extract_markup(hostile, "svg") is None
    assert time.perf_counter() - start < 1
    # A figure nested in an SVG keeps its own calkit when the outer one's
    # is replaced
    inner = calkit.kits.embed_markup(b"<svg><rect/></svg>", b"inner", "svg")
    outer = b"<svg>" + inner + b"<circle/></svg>"
    data = calkit.kits.embed(outer, "outer.svg", b"outer-1")
    assert calkit.kits.extract_markup(data, "svg") == (b"outer-1", outer)
    data = calkit.kits.embed(data, "outer.svg", b"outer-2")
    assert calkit.kits.extract_markup(data, "svg") == (b"outer-2", outer)
    assert calkit.kits.extract_markup(inner, "svg") == (
        b"inner",
        b"<svg><rect/></svg>",
    )
    # An HTML page with an inline SVG is HTML, and quoting the opening tag
    # before an unrelated script isn't mistaken for a calkit
    page = b"<html><body><svg><path/></svg><p>Hi</p></body></html>"
    assert calkit.kits.get_format(page, "page.html") == "html"
    doc_page = (
        b"<html><body><pre>"
        + calkit.kits.MARKUP_BLOCKS["html"][0]
        + b"</pre><script>1</script></body></html>"
    )
    assert calkit.kits.extract_markup(doc_page, "html") is None
    # Iterated stages match their locked outputs in matches_pipeline
    iter_manifest = make_manifest({})
    iter_manifest["artifact"]["stage"] = "each"
    iter_kit = write_zip(
        {
            MANIFEST_NAME: (json.dumps(iter_manifest).encode(), False),
            PROJECT_DIR + "dvc.yaml": (
                b"stages:\n  each:\n    foreach: [1]\n    do:\n      cmd: echo\n",
                False,
            ),
            PROJECT_DIR + "dvc.lock": (
                (
                    "stages:\n  each@1:\n    outs:\n"
                    f"    - path: fig.png\n      md5: {hashlib.md5(png).hexdigest()}\n"
                ).encode(),
                False,
            ),
        }
    )
    iter_embedded = calkit.kits.EmbeddedKit(
        kit=iter_kit,
        artifact=png,
        manifest=calkit.kits.Manifest.model_validate(iter_manifest),
    )
    assert iter_embedded.matches_pipeline is True
    # A PDF saved again after its calkit was added no longer matches, and
    # its calkit can't be replaced without losing that change
    doc = pdfium.PdfDocument.new()
    doc.new_page(100, 100)
    doc.new_page(100, 100)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    pdf = buf.getvalue()
    pdf_manifest = make_manifest({})
    pdf_manifest["artifact"] |= {
        "path": "paper.pdf",
        "size": len(pdf),
        "sha256": hashlib.sha256(pdf).hexdigest(),
    }
    pdf_kit = write_zip(
        {MANIFEST_NAME: (json.dumps(pdf_manifest).encode(), False)}
    )
    with_kit = calkit.kits.embed_pdf(pdf, pdf_kit)
    doc = pdfium.PdfDocument(with_kit)
    doc.del_page(1)
    buf = io.BytesIO()
    doc.save(buf, flags=pdfium.raw.FPDF_INCREMENTAL)
    doc.close()
    edited = tmp_path / "edited.pdf"
    edited.write_bytes(buf.getvalue())
    assert calkit.kits.read(str(tmp_path / "edited.pdf")) is not None
    edited_kit = calkit.kits.read(str(edited))
    assert edited_kit is not None
    assert not edited_kit.artifact_unchanged
    with pytest.raises(calkit.kits.KitError, match="changed after"):
        calkit.kits.embed(buf.getvalue(), "paper.pdf", pdf_kit)
    unedited = tmp_path / "unedited.pdf"
    unedited.write_bytes(with_kit)
    unedited_kit = calkit.kits.read(str(unedited))
    assert unedited_kit is not None
    assert unedited_kit.artifact_unchanged
    # A negative size in a PDF manifest can't slice from the end
    neg_manifest = make_manifest({})
    neg_manifest["artifact"] |= {
        "path": "paper.pdf",
        "size": -10,
        "sha256": hashlib.sha256(pdf).hexdigest(),
    }
    neg_kit = write_zip(
        {MANIFEST_NAME: (json.dumps(neg_manifest).encode(), False)}
    )
    neg_pdf = tmp_path / "neg.pdf"
    neg_pdf.write_bytes(calkit.kits.embed_pdf(pdf, neg_kit))
    neg_read = calkit.kits.read(str(neg_pdf))
    assert neg_read is not None
    assert not neg_read.artifact_unchanged


def test_scrub():
    assert calkit.kits.scrub_url("https://tok@github.com/a/b.git") == (
        "https://github.com/a/b.git"
    )
    assert calkit.kits.scrub_url("https://u:p@host/x") == "https://host/x"
    assert calkit.kits.scrub_url("ssh://git:pw@host/a/b") == (
        "ssh://git@host/a/b"
    )
    assert calkit.kits.scrub_url("git@github.com:a/b.git") == (
        "git@github.com:a/b.git"
    )
    config = (
        "[core]\n    remote = storage\n"
        "    site_cache_dir = /Users/me/site\n"
        "['remote \"storage\"']\n    url = s3://bucket/x\n"
        "    access_key_id = AKIA\n    secret_access_key = shh\n"
        "['remote \"web\"']\n    url = https://user:pw@host/dvc\n"
        "[cache]\n    dir = /Users/me/cache\n"
    )
    scrubbed = calkit.kits.scrub_dvc_config(config)
    assert "remote = storage" in scrubbed
    assert "url = s3://bucket/x" in scrubbed
    assert "url = https://host/dvc" in scrubbed
    for secret in ["AKIA", "shh", "pw", "/Users/me"]:
        assert secret not in scrubbed
    # Paths in dvc.lock are relative to their stage's wdir
    stage_io = calkit.kits.get_stage_io(
        {
            "stages": {
                "plot": {
                    "deps": [{"path": "plot.py", "md5": "a"}],
                    "outs": [{"path": "../figs/f.png", "md5": "b"}],
                },
                "each@1": {"outs": [{"path": "out.txt", "md5": "c"}]},
            }
        },
        {
            "stages": {
                "plot": {"wdir": "scripts"},
                "each": {"foreach": [1], "do": {"wdir": "sub"}},
            }
        },
    )
    assert stage_io["plot"] == {
        "deps": [("scripts/plot.py", "a")],
        "outs": [("figs/f.png", "b")],
    }
    assert stage_io["each@1"]["outs"] == [("sub/out.txt", "c")]


def test_get_record_tag_name():
    for path in [
        "figures/plot.png",
        ".hidden/a b..c.lock/x:y?.png",
        "dir./a.lock.lock/fig.png",
    ]:
        manifest = calkit.kits.Manifest(
            created_with="test",
            artifact=calkit.kits.KitArtifact(
                path=path, size=1, sha256="0" * 64, stage="s"
            ),
            source=calkit.kits.KitSource(up_to_date=True),
            files=[],
        )
        name = calkit.kits.get_record_tag_name(b"kit", manifest, "2026-11-27")
        assert name.startswith("kit/")
        assert name.endswith(
            "/2026-11-27-" + hashlib.sha256(b"kit").hexdigest()[:7]
        )
        subprocess.check_call(["git", "check-ref-format", f"refs/tags/{name}"])
