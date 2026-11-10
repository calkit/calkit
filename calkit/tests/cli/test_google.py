import json
import os
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import calkit
from calkit.cli.export import export_app
from calkit.cli.google import (
    get_hub_response,
    record_edit_times,
)
from calkit.cli.import_ import import_app
from calkit.cli.main import app
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

    # What the presentation shows, which is nothing at first
    components = []
    put = []

    def hub_get(path, **kwargs):
        if path.endswith("/components"):
            return [dict(c) for c in components]
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

    def hub_put(path, **kwargs):
        put.append((path, kwargs["json"]))
        return {
            "values": len(kwargs["json"]["values"]),
            "tables": len(kwargs["json"]["tables"]),
            "modified_time": decks[pid]["modified_time"],
        }

    monkeypatch.setattr(calkit.hub, "get", hub_get)
    monkeypatch.setattr(calkit.hub, "post", hub_post)
    monkeypatch.setattr(calkit.hub, "put", hub_put)
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
        "inputs": ["figures/rates.png"],
        "outputs": ["poster/poster.pdf", "poster/poster.pptx"],
    }
    edit_time_path = f".calkit/google/{pid}.json"
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
    # Nor can an output of another stage, and a presentation that can't be
    # added isn't created first
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"]["stages"]["build-notes"] = {
        "kind": "shell-command",
        "command": "echo",
        "environment": "_system",
        "outputs": ["notes.pptx"],
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    n_posted = len(posted)
    res = runner.invoke(
        new_app, ["google-slides", "--title", "Notes", "--path", "notes.pdf"]
    )
    assert res.exit_code != 0
    assert "notes.pptx is already an output of stage 'build-notes'" in (
        res.output
    )
    assert len(posted) == n_posted
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
        export_app,
        [
            "google-slides",
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
        export_app, ["google-slides", url, "-o", "poster/poster.pdf"]
    )
    assert res.exit_code == 0, res.output
    assert "poster/poster.pdf is unchanged, so it was kept" in res.output
    assert os.path.getmtime("poster/poster.pdf") == mtime

    # The edit time recorded is from before exporting, so an edit made while
    # exporting is seen next time
    def hub_get_edited(path, **kwargs):
        resp = hub_get(path, **kwargs)
        if path.endswith("/export"):
            decks[pid]["modified_time"] = "t4"
        return resp

    monkeypatch.setattr(calkit.hub, "get", hub_get_edited)
    res = runner.invoke(
        export_app, ["google-slides", url, "-o", "poster/poster.pdf"]
    )
    assert res.exit_code == 0, res.output
    with open(edit_time_path) as f:
        assert json.load(f) == {"modified_time": "t2"}
    monkeypatch.setattr(calkit.hub, "get", hub_get)
    # Only a presentation edited since is reported
    ck_info = calkit.load_calkit_info()
    assert record_edit_times(ck_info) == ["export-poster"]
    assert record_edit_times(ck_info) == []
    decks[other]["modified_time"] = "t3"
    assert record_edit_times(ck_info) == ["export-talk"]

    # One that can't be checked doesn't stop the others being recorded
    def hub_get_failing(path, **kwargs):
        if path.endswith(other):
            raise RuntimeError("404: Not found")
        return hub_get(path, **kwargs)

    decks[pid]["modified_time"] = "t5"
    monkeypatch.setattr(calkit.hub, "get", hub_get_failing)
    with pytest.raises(RuntimeError, match="404"):
        record_edit_times(ck_info)
    with open(edit_time_path) as f:
        assert json.load(f) == {"modified_time": "t5"}
    monkeypatch.setattr(calkit.hub, "get", hub_get)
    # A subproject's presentations are checked too
    os.makedirs("sub")
    with open("sub/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "export-sub": {
                            "kind": "google-slides-export",
                            "presentation_url": url,
                            "outputs": ["sub.pdf"],
                        }
                    }
                }
            },
            f,
        )
    ck_info["subprojects"] = [{"path": "sub"}]
    decks[pid]["modified_time"] = "t6"
    assert record_edit_times(ck_info) == [
        "export-poster",
        "sub/dvc.yaml:export-sub",
    ]
    with open(f"sub/.calkit/google/{pid}.json") as f:
        assert json.load(f) == {"modified_time": "t6"}
    res = runner.invoke(app, ["pull", "google"])
    assert res.exit_code == 0, res.output
    assert "Git pulling" not in res.output
    assert "No Google Slides presentations were edited" in res.output
    # Figures Slides can't show are refused before anything is sent
    n_posted = len(posted)
    res = runner.invoke(
        export_app,
        ["google-slides", url, "-o", "p.pdf", "--figure", "figures/rates.pdf"],
    )
    assert res.exit_code != 0
    assert "PNG, JPEG, or GIF" in res.output
    assert len(posted) == n_posted
    # Text boxes and tables tagged with values and tables from the inputs
    # are filled in, and what it shows is recorded for the hub
    os.makedirs("results", exist_ok=True)
    with open("results/wake.json", "w") as f:
        json.dump({"mean_deficit": 0.12345}, f)
    with open("results/cases.csv", "w") as f:
        f.write("case,u\nA,1.5\n")
    value_tag = "calkit:results/wake.json#mean_deficit:.2f"
    components += [
        {
            "kind": "figure",
            "path": "figures/rates.png",
            "key": None,
            "format": None,
            "slide_id": "s1",
            "element_id": "img",
            "tag": "calkit:figures/rates.png",
        },
        {
            "kind": "value",
            "path": "results/wake.json",
            "key": "mean_deficit",
            "format": ".2f",
            "slide_id": "s1",
            "element_id": "box",
            "tag": value_tag,
            "text": "0.11",
        },
        {
            "kind": "table",
            "path": "results/cases.csv",
            "key": None,
            "format": None,
            "slide_id": "s2",
            "element_id": "tbl",
            "tag": "calkit:results/cases.csv",
            "rows": [["old"]],
        },
    ]
    res = runner.invoke(
        export_app,
        [
            "google-slides",
            url,
            "-o",
            "poster/poster.pdf",
            "--input",
            "results/wake.json",
        ],
    )
    assert res.exit_code == 0, res.output
    assert put[-1][1] == {
        "values": {value_tag: "0.12"},
        "tables": {"calkit:results/cases.csv": [["case", "u"], ["A", "1.5"]]},
    }
    assert "Updated 1 value(s) and 1 table(s)" in res.output
    # One that isn't an input is still filled in, but changing it wouldn't
    # put the presentation out of date
    assert "results/cases.csv isn't an input of the stage" in res.output
    with open(f".calkit/google/{pid}-components.json") as f:
        assert json.load(f) == [
            {
                k: c[k]
                for k in ["kind", "path", "key", "format", "slide_id"]
                + ["element_id"]
            }
            for c in components
        ]
    # A key that isn't there says where it's shown
    components[1] = dict(components[1], tag="calkit:results/wake.json#nope")
    components[1]["key"] = "nope"
    res = runner.invoke(
        export_app, ["google-slides", url, "-o", "poster/poster.pdf"]
    )
    assert res.exit_code != 0
    assert "results/wake.json has no nope" in res.output
    assert "text box tagged 'calkit:results/wake.json#nope'" in res.output
    components.clear()
    # Without Google connected, someone at a terminal is sent to connect it,
    # and the request is made again once they have
    import time
    import webbrowser

    import requests

    connected = [False, False, True]
    opened = []

    def hub_get_accounts(path, **kwargs):
        assert path == "/user/connected-accounts"
        return {"google": connected.pop(0) if len(connected) > 1 else True}

    def hub_post_once(path, **kwargs):
        if not opened:
            resp = requests.Response()
            resp.status_code = 403
            raise requests.HTTPError(
                "403: Connect Google Drive", response=resp
            )
        return {"ok": True}

    monkeypatch.setattr(calkit.hub, "get", hub_get_accounts)
    monkeypatch.setattr(calkit.hub, "post", hub_post_once)
    monkeypatch.setattr(calkit.hub, "get_hub_url", lambda: "http://hub/")
    monkeypatch.setattr(webbrowser, "open", opened.append)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr("calkit.core.is_tty", lambda: False)
    with pytest.raises(requests.HTTPError):
        get_hub_response("post", "/user/google/presentations")
    assert not opened
    monkeypatch.setattr("calkit.core.is_tty", lambda: True)
    assert get_hub_response("post", "/user/google/presentations") == {
        "ok": True
    }
    assert opened == [
        "http://hub/settings?tab=connected-accounts&connect=google"
    ]
    assert not connected[:-1]
    # A 403 with Google connected is some other refusal, so it's raised
    opened.clear()
    with pytest.raises(requests.HTTPError):
        get_hub_response("post", "/user/google/presentations")
    assert not opened


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
        if path.endswith("/components"):
            return []
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
    }
    # Its stage is found from the slides the stage exports
    assert (
        calkit.pipeline.get_stage_for_output("figures/setup.pdf", ck_info)
        == "export-diagrams"
    )
    repo = calkit.git.get_repo()
    assert not repo.git.status("--porcelain", ".calkit/google")
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
        "google-slides",
        url,
        "--slide",
        "figures/setup.pdf=s2",
        "--slide",
        "figures/setup.png=s2",
    ]
    res = runner.invoke(export_app, args)
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
    res = runner.invoke(export_app, args)
    assert res.exit_code != 0
    assert "is 'copied'" in res.output
    res = runner.invoke(export_app, ["google-slides", url, "--slide", "bad"])
    assert res.exit_code != 0
    assert "its figure's path and its ID" in res.output
    # Nothing drawn on the slide can't make a figure
    res = runner.invoke(
        export_app, ["google-slides", url, "--slide", "figures/t.pdf=title"]
    )
    assert res.exit_code != 0
    assert "Nothing is drawn" in res.output
