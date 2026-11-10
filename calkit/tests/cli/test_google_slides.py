import json
import os
import subprocess

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
