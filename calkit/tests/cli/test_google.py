import json
import os
import subprocess

import pytest
from typer.testing import CliRunner

import calkit
from calkit.cli.export import export_app
from calkit.cli.google import (
    get_hub_response,
    get_presentation_response,
    link_presentation,
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
    # With the project on the hub, the presentation is asked for there, so
    # it's reached through whoever linked it, and through the user's own
    # Google account if the hub doesn't know the project
    asked = []

    def hub_get_project(path, **kwargs):
        asked.append(path)
        if path.startswith("/projects/me/unknown/"):
            resp = requests.Response()
            resp.status_code = 404
            raise requests.HTTPError("404: Not Found", response=resp)
        return {"modified_time": "t9"}

    monkeypatch.setattr(calkit.hub, "get", hub_get_project)
    monkeypatch.setattr(calkit, "detect_project_name", lambda **kw: "me/known")
    assert get_presentation_response("get", pid, "/export") == {
        "modified_time": "t9"
    }
    assert asked == [f"/projects/me/known/google/presentations/{pid}/export"]
    monkeypatch.setattr(
        calkit, "detect_project_name", lambda **kw: "me/unknown"
    )
    asked.clear()
    get_presentation_response("get", pid, connect=False)
    assert asked == [
        f"/projects/me/unknown/google/presentations/{pid}",
        f"/user/google/presentations/{pid}",
    ]
    # Adding one links it to the project on the hub, which a hub that
    # doesn't know the project quietly doesn't
    linked = []

    def hub_post_link(path, **kwargs):
        linked.append(path)
        if "unknown" in path:
            resp = requests.Response()
            resp.status_code = 404
            raise requests.HTTPError("404: Not Found", response=resp)
        return {}

    monkeypatch.setattr(calkit.hub, "post", hub_post_link)
    link_presentation(pid)
    monkeypatch.setattr(calkit, "detect_project_name", lambda **kw: "me/known")
    link_presentation(pid)
    assert linked == [
        f"/projects/me/unknown/google/presentations/{pid}",
        f"/projects/me/known/google/presentations/{pid}",
    ]
