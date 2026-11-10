import json
import os
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import calkit
from calkit.cli.google_slides import google_slides_app, record_edit_times
from calkit.cli.import_ import import_app
from calkit.cli.new import new_app

runner = CliRunner()


def test_google_slides(tmp_dir, monkeypatch):
    subprocess.run(["calkit", "init"], check=True)
    pid = "1AbCdEfGhIjKlMnOpQrStUv"
    url = f"https://docs.google.com/presentation/d/{pid}/edit"
    other = "2AbCdEfGhIjKlMnOpQrStUv"
    decks = {
        pid: {"id": pid, "title": "Poster", "url": url, "modified_time": "t1"},
        other: {
            "id": other,
            "title": "Talk",
            "url": f"https://docs.google.com/presentation/d/{other}/edit",
            "modified_time": "t1",
        },
    }
    posted = []

    def hub_get(path, **kwargs):
        if path.endswith("/export"):
            fmt = kwargs["params"]["format"]

            class Resp:
                content = f"{fmt} of {decks[pid]['modified_time']}".encode()

            return Resp()
        return dict(decks[path.split("/")[-1]])

    def hub_post(path, **kwargs):
        posted.append((path, kwargs))
        if path == "/user/google/presentations":
            return dict(decks[pid], title=kwargs["json"]["title"])
        # Putting a figure in edits the presentation
        decks[pid]["modified_time"] = "t2"
        return {"replaced": 0, "added": True, "modified_time": "t2"}

    monkeypatch.setattr(calkit.hub, "get", hub_get)
    monkeypatch.setattr(calkit.hub, "post", hub_post)
    os.makedirs("figures")
    with open("figures/rates.png", "wb") as f:
        f.write(b"png")
    res = runner.invoke(
        new_app,
        [
            "google-slides",
            "--title",
            "My poster",
            "--path",
            "poster/poster.pdf",
            "--kind",
            "poster",
            "--figure",
            "figures/rates.png",
        ],
    )
    assert res.exit_code == 0, res.output
    ck_info = calkit.load_calkit_info()
    assert ck_info["presentations"] == [
        {
            "path": "poster/poster.pdf",
            "title": "My poster",
            "kind": "poster",
        }
    ]
    assert ck_info["pipeline"]["stages"]["export-poster"] == {
        "kind": "google-slides-export",
        "presentation_url": url,
        "figures": ["figures/rates.png"],
        "outputs": ["poster/poster.pdf", "poster/poster.pptx"],
    }
    edit_time_path = f".calkit/google-slides/{pid}.json"
    with open(edit_time_path) as f:
        assert json.load(f) == {"modified_time": "t1"}
    repo = calkit.git.get_repo()
    assert (
        repo.head.commit.message.strip()
        == "Add presentation poster/poster.pdf"
    )
    assert not repo.git.status("--porcelain", edit_time_path)
    # The same path or stage can't be added twice
    res = runner.invoke(
        import_app, ["google-slides", url, "--path", "poster/poster.pdf"]
    )
    assert res.exit_code != 0
    assert "already exists" in res.output
    res = runner.invoke(
        import_app,
        [
            "google-slides",
            decks[other]["url"],
            "--path",
            "talk.pdf",
            "--no-pptx",
            "--no-commit",
        ],
    )
    assert res.exit_code == 0, res.output
    stages = calkit.load_calkit_info()["pipeline"]["stages"]
    assert stages["export-talk"]["outputs"] == ["talk.pdf"]
    # Exporting puts the figures in first, then records that edit
    res = runner.invoke(
        google_slides_app,
        [
            "export",
            url,
            "-o",
            "poster/poster.pdf",
            "-o",
            "poster/poster.pptx",
            "--figure",
            "figures/rates.png",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "Added figures/rates.png to the first slide" in res.output
    assert posted[-1][1]["params"] == {"path": "figures/rates.png"}
    with open("poster/poster.pdf") as f:
        assert f.read() == "pdf of t2"
    with open("poster/poster.pptx") as f:
        assert f.read() == "pptx of t2"
    with open(edit_time_path) as f:
        assert json.load(f) == {"modified_time": "t2"}
    # Exporting what's already there keeps the file, so nothing downstream
    # of it reruns
    mtime = os.path.getmtime("poster/poster.pdf")
    res = runner.invoke(
        google_slides_app, ["export", url, "-o", "poster/poster.pdf"]
    )
    assert res.exit_code == 0, res.output
    assert "poster/poster.pdf is unchanged, so it was kept" in res.output
    assert os.path.getmtime("poster/poster.pdf") == mtime
    # Only a presentation edited since is reported
    ck_info = calkit.load_calkit_info()
    assert record_edit_times(ck_info) == []
    decks[other]["modified_time"] = "t3"
    assert record_edit_times(ck_info) == ["export-talk"]
    res = runner.invoke(google_slides_app, ["pull"])
    assert "No Google Slides presentations were edited" in res.output
    # Figures Slides can't show are refused before anything is sent
    n_posted = len(posted)
    res = runner.invoke(
        google_slides_app,
        ["export", url, "-o", "p.pdf", "--figure", "figures/rates.pdf"],
    )
    assert res.exit_code != 0
    assert "PNG, JPEG, or GIF" in res.output
    assert len(posted) == n_posted


def test_google_slide_figures(tmp_dir, monkeypatch):
    import io

    import pypdfium2 as pdfium

    subprocess.run(["calkit", "init"], check=True)
    pid = "1AbCdEfGhIjKlMnOpQrStUv"
    url = f"https://docs.google.com/presentation/d/{pid}/edit"
    doc = pdfium.PdfDocument.new()
    doc.new_page(720, 405)
    doc.new_page(720, 405)
    buf = io.BytesIO()
    doc.save(buf)
    slides = [
        {
            "id": "title",
            "notes": "",
            "notes_id": "n1",
            "is_skipped": False,
            "bounds": None,
        },
        {
            "id": "s2",
            "notes": "",
            "notes_id": "n2",
            "is_skipped": False,
            "bounds": [200.0, 100.0, 560.0, 220.0],
        },
    ]
    tagged = []

    def hub_get(path, **kwargs):
        if path.endswith("/slides"):
            return {"page_size": [720.0, 405.0], "slides": slides}
        if path.endswith("/export"):
            return SimpleNamespace(content=buf.getvalue())
        return {
            "id": pid,
            "title": "Diagrams",
            "url": url,
            "modified_time": "t1",
        }

    def hub_post(path, **kwargs):
        tagged.append(kwargs["json"]["tags"])
        return {"tagged": 1}

    monkeypatch.setattr(calkit.hub, "get", hub_get)
    monkeypatch.setattr(calkit.hub, "post", hub_post)
    # The figure's slide comes from the URL of the slide being viewed
    res = runner.invoke(
        new_app,
        [
            "figure",
            "figures/setup.pdf",
            "--title",
            "Setup",
            "--google-slide",
            url,
        ],
    )
    assert res.exit_code != 0
    assert "doesn't say which slide" in res.output
    for path in ["figures/setup.pdf", "figures/setup.png"]:
        res = runner.invoke(
            new_app,
            [
                "figure",
                path,
                "--title",
                "Setup",
                "--google-slide",
                f"{url}#slide=id.s2",
            ],
        )
        assert res.exit_code == 0, res.output
    ck_info = calkit.load_calkit_info()
    assert ck_info["pipeline"]["stages"]["export-diagrams"] == {
        "kind": "google-slides-export",
        "presentation_url": url,
        "slides": {"figures/setup.pdf": "s2", "figures/setup.png": "s2"},
    }
    assert ck_info["figures"][0] == {
        "path": "figures/setup.pdf",
        "title": "Setup",
        "stage": "export-diagrams",
    }
    repo = calkit.git.get_repo()
    assert not repo.git.status("--porcelain", ".calkit/google-slides")
    res = runner.invoke(
        new_app,
        [
            "figure",
            "figures/other.pdf",
            "--title",
            "Other",
            "--google-slide",
            f"{url}#slide=id.missing",
        ],
    )
    assert res.exit_code != 0
    assert "no slide 'missing'" in res.output
    # Exporting tags the slide, and crops it to what's drawn, plus a margin
    args = [
        "export",
        url,
        "--slide",
        "figures/setup.pdf=s2",
        "--slide",
        "figures/setup.png=s2",
    ]
    res = runner.invoke(google_slides_app, args)
    assert res.exit_code == 0, res.output
    assert tagged[-1] == {
        "figures/setup.pdf": "s2",
        "figures/setup.png": "s2",
    }
    assert pdfium.PdfDocument("figures/setup.pdf")[0].get_size() == (
        pytest.approx((368, 128))
    )
    assert os.path.getsize("figures/setup.png") > 0
    # A slide deleted since is reported, pointing at one tagged for it
    slides[1]["id"] = "copied"
    slides[1]["notes"] = "calkit:figures/setup.pdf\n"
    res = runner.invoke(google_slides_app, args)
    assert res.exit_code != 0
    assert "is 'copied'" in res.output
    res = runner.invoke(google_slides_app, ["export", url, "--slide", "bad"])
    assert res.exit_code != 0
    assert "its figure's path and its ID" in res.output
    # Nothing drawn on the slide can't make a figure
    res = runner.invoke(
        google_slides_app, ["export", url, "--slide", "figures/t.pdf=title"]
    )
    assert res.exit_code != 0
    assert "Nothing is drawn" in res.output
