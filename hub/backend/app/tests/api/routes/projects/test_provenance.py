import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.pipeline import PipelineAtRef
from app.pipeline import StageStatus as PipelineStageStatus

MODULE = "app.api.routes.projects.provenance"


def test_get_project_provenance(client: TestClient) -> None:
    files = {
        "results/metrics.json": json.dumps(
            {"rmse": 0.12, "fit": {"slope": 1.23}}
        ),
        "scripts/analyze.py": "print()",
        "data/downloaded/a.csv": "x\n1\n",
        "data/downloaded/notes.csv": "x\n2\n",
        "paper/drawn.svg": "",
        "paper/exported.png": "",
        "paper/pasted.png": "",
        "paper/diagram.png": "",
        "paper/box.png": "",
        "paper/from-src.png": "old",
        "paper/from-stored.png": "old",
        "paper/from-git.png": "",
        # The other project's, which has moved on
        "figs/plot.png": "new",
        ".calkit/imports.json": json.dumps(
            {
                path: {"hash": "sha256:" + hashlib.sha256(b"old").hexdigest()}
                for path in ["paper/from-src.png", "paper/from-stored.png"]
            }
        ),
    }
    # In object storage, inside a directory a stage outputs
    stored = {
        "results/sweep/summary.json": json.dumps({"best": 7}),
        # The other project's, kept with DVC, which has moved on too
        "figs/stored.png": "new",
    }
    tree = SimpleNamespace(
        is_file=lambda path: path in files,
        is_dir=lambda path: path == "data/downloaded",
        listdir=lambda path: (
            ["a.csv", "notes.csv"] if path == "data/downloaded" else []
        ),
        read_text=lambda path: files[path],
        read_bytes=lambda path: files[path].encode(),
    )
    ck_info = {
        "environments": {"py": {"kind": "uv", "path": "pyproject.toml"}},
        "datasets": [
            {
                "path": "data/downloaded",
                "imported_from": "https://x.org/d.zip",
            },
            # Listed after the folder it's in, but it's the file's own
            {
                "path": "data/downloaded/notes.csv",
                "created_by": {"name": "Ada"},
            },
        ],
        "figures": [
            {
                "path": "paper/drawn.svg",
                "created_by": {"name": "Ada", "with_ai": "Claude"},
            },
            # Exported from something, so a person can't be its origin
            {"path": "paper/exported.png", "created_by": {"name": "Ada"}},
            # Only described, so nobody else can check it
            {"path": "paper/box.png", "imported_from": "Our Box folder"},
            {
                "path": "paper/from-src.png",
                "imported_from": {"project": "o/src", "path": "figs/plot.png"},
            },
            {
                "path": "paper/from-stored.png",
                "imported_from": {
                    "project": "o/src",
                    "path": "figs/stored.png",
                },
            },
            {
                "path": "paper/from-git.png",
                "imported_from": {
                    "git_repo_url": "https://github.com/a/b",
                    "path": "fig.png",
                },
            },
        ],
        "pipeline": {
            "stages": {
                "analyze": {
                    "kind": "python-script",
                    "script_path": "scripts/analyze.py",
                    "environment": "py",
                    "outputs": ["results/metrics.json"],
                },
                # Declared but never run, so it isn't in dvc.lock
                "plot": {
                    "kind": "python-script",
                    "script_path": "plot.py",
                    "environment": "py",
                    "wdir": "figs",
                    "outputs": ["out.png"],
                },
                # Exported manually from a file someone made
                "export-diagram": {
                    "kind": "manual-step",
                    "message": "In Photoshop, export paper/diagram.png",
                    "inputs": ["figs/diagram.psd"],
                    "outputs": ["paper/diagram.png"],
                },
                "export-setup": {
                    "kind": "inkscape-export",
                    "source_path": "figs/setup.svg",
                    "outputs": ["paper/setup.png"],
                },
                # Puts the plot beside the paper, which includes it there
                "copy": {
                    "kind": "map-paths",
                    "paths": [
                        {
                            "kind": "file-to-file",
                            "src": "figs/out.png",
                            "dest": "paper/out.png",
                        },
                        {
                            "kind": "file-to-file",
                            "src": "paper/from-src.png",
                            "dest": "slides/from-src.png",
                        },
                    ],
                },
            }
        },
    }
    pipeline = PipelineAtRef(
        dvc_yaml={
            "stages": {
                # Reads a folder, relative to its wdir
                "summarize": {
                    "cmd": "python summarize.py",
                    "wdir": "figs",
                    "deps": ["summarize.py", "../data/downloaded"],
                },
                # Iterated, so what it reads is only concrete in dvc.lock
                "sweep": {
                    "foreach": ["a"],
                    "do": {"cmd": "run ${item}", "deps": ["${item}.csv"]},
                },
            }
        },
        dvc_lock={
            "stages": {
                "sweep@a": {"deps": [{"path": "data/raw.csv"}]},
                "analyze": {
                    "deps": [
                        {"path": "scripts/analyze.py"},
                        {"path": "data/raw.csv"},
                        {"path": ".calkit/env-locks/py.json"},
                        # The environment's, which aren't what it reads
                        {"path": "uv.lock"},
                        {"path": "pyproject.toml"},
                        {"path": ".python-version"},
                    ],
                    "outs": [{"path": "results/metrics.json"}],
                },
            }
        },
        statuses={
            "analyze": PipelineStageStatus(status="stale"),
            "copy": PipelineStageStatus(status="stale"),
        },
        frozen=set(),
    )

    def read(project, tree, path, max_bytes, session, current_user):
        if path not in files | stored:
            raise HTTPException(404, f"'{path}' is not a file in this project")
        return (files | stored)[path].encode()

    def get(params: str) -> dict:
        with (
            patch(f"{MODULE}.app.projects.get_project"),
            patch(f"{MODULE}.get_repo"),
            patch(
                f"{MODULE}.app.projects.get_ck_info_for_ref",
                return_value=ck_info,
            ),
            patch(f"{MODULE}.get_repo_tree_for_ref", return_value=tree),
            patch(f"{MODULE}.pipeline_at_ref", return_value=pipeline),
            patch(
                f"{MODULE}.app.projects.read_project_file", side_effect=read
            ),
            patch(
                f"{MODULE}.app.projects.dvc_outputs_from_tree",
                return_value={p: {"md5": "x"} for p in stored},
            ),
        ):
            response = client.get(f"/projects/o/p/provenance?{params}")
        assert response.status_code == 200, response.text
        return response.json()

    # A value, the stage that computes it, what to edit, what it reads,
    # and that it's out of date
    body = get("path=results/metrics.json&key=fit.slope")
    assert body["exists"]
    assert body["value"] == 1.23
    assert body["stage"] == "analyze"
    assert body["stage_kind"] == "python-script"
    assert body["source"] == "scripts/analyze.py"
    # Neither Calkit's bookkeeping nor the source shown on its own
    assert body["inputs"] == ["data/raw.csv"]
    assert body["stage_status"]["status"] == "stale"
    assert body["stale_reason"] == "pipeline"
    # What it reads has no recorded origin, which is reported with the
    # chain leading to it
    assert body["gaps"] == [
        {
            "path": "data/raw.csv",
            "steps": [
                {"path": "results/metrics.json", "stage": "analyze"},
                {"path": "data/raw.csv", "stage": None},
            ],
            "unchecked": False,
        }
    ]
    assert body["origin"] is None
    # A subtree is a value too
    assert get("path=results/metrics.json&key=fit")["value"] == {"slope": 1.23}
    # Without a key, a results file is read whole, e.g., to browse it
    assert get("path=results/metrics.json")["value"] == {
        "rmse": 0.12,
        "fit": {"slope": 1.23},
    }
    # A key the file doesn't have says so
    body = get("path=results/metrics.json&key=nope")
    assert body["value"] is None
    assert "nope" in body["value_error"]
    # A file inside a directory output is read from storage
    body = get("path=results/sweep/summary.json&key=best")
    assert body["exists"]
    assert body["value"] == 7
    # A file that isn't there says so, rather than having no value
    body = get("path=results/gone.json&key=rmse")
    assert not body["exists"]
    assert body["value"] is None
    assert "results/gone.json" in body["value_error"]
    # A stage never run is still found from calkit.yaml, relative to its
    # wdir, though nothing has produced the file yet
    body = get("path=figs/out.png")
    assert not body["exists"]
    assert body["stage"] == "plot"
    assert body["source"] == "figs/plot.py"
    assert body["stage_status"] is None
    # A copy is described by the stage that made the original, and is out
    # of date while the copy is
    body = get("path=paper/out.png")
    assert body["copied_from"] == "figs/out.png"
    assert body["copy_stage"] == "copy"
    assert body["stage"] == "plot"
    assert body["source"] == "figs/plot.py"
    assert body["stale_reason"] == "pipeline"
    # A stage dvc.yaml doesn't have yet is trusted
    assert body["gaps"] == []
    assert get("path=figs/out.png")["copied_from"] is None
    # What calkit.yaml records for something no stage makes, including for
    # a folder it's in
    body = get("path=data/downloaded/a.csv")
    assert body["stage"] is None
    assert body["origin"] == "Imported from https://x.org/d.zip"
    assert body["origin_url"] == "https://x.org/d.zip"
    assert body["origin_path"] == "data/downloaded"
    assert body["gaps"] == []
    # A file's own entry says more than its folder's
    body = get("path=data/downloaded/notes.csv")
    assert body["origin"] == "Created by Ada"
    assert body["origin_path"] is None
    body = get("path=paper/drawn.svg")
    assert body["origin"] == "Created by Ada with Claude"
    assert body["origin_url"] is None
    assert body["origin_path"] is None
    assert body["gaps"] == []
    # A figure exported manually says what to do, and what it's from
    body = get("path=paper/diagram.png")
    assert body["stage"] == "export-diagram"
    assert body["stage_kind"] == "manual-step"
    assert body["message"] == "In Photoshop, export paper/diagram.png"
    assert body["source"] is None
    assert body["stage_app"] is None
    # Exported by an app as the pipeline runs
    body = get("path=paper/setup.png")
    assert body["stage_kind"] == "inkscape-export"
    assert body["stage_app"] == "Inkscape"
    assert body["source"] == "figs/setup.svg"
    # A figure nothing accounts for is a gap itself
    for path in ["paper/pasted.png", "paper/exported.png"]:
        body = get(f"path={path}")
        assert body["origin"] is None
        assert body["gaps"] == [
            {
                "path": path,
                "steps": [{"path": path, "stage": None}],
                "unchecked": False,
            }
        ]
    # Imported from somewhere nobody else can check
    body = get("path=paper/box.png")
    assert body["origin"] == "Our Box folder"
    assert [g["unchecked"] for g in body["gaps"]] == [True]
    assert not body["updatable"]
    # Imported from another project, which has something newer
    body = get("path=paper/from-src.png")
    assert body["origin"] == "Imported from o/src/figs/plot.png"
    assert body["origin_url"].endswith("/o/src/files?path=figs/plot.png")
    assert body["updatable"]
    assert body["update_available"]
    # Also when the source is kept with DVC rather than Git
    body = get("path=paper/from-stored.png")
    assert body["updatable"]
    assert body["update_available"]
    # A copy of an import shows where it came from, but is updated through
    # the import itself
    body = get("path=slides/from-src.png")
    assert body["origin"] == "Imported from o/src/figs/plot.png"
    assert body["copied_from"] == "paper/from-src.png"
    assert not body["updatable"]
    # Imported from a Git repo, which would have to be cloned to tell
    body = get("path=paper/from-git.png")
    assert body["updatable"]
    assert body["update_available"] is None
    # Nothing produces an authored file
    body = get("path=scripts/analyze.py")
    assert body["exists"]
    assert body["stage"] is None
    # and it isn't a results file, so there's no value to read
    assert body["value"] is None
    assert body["value_error"] is None
    # and code needs no recorded origin
    assert body["gaps"] == []
    # The stages that read something, or a folder it's in
    assert body["input_to_stages"] == ["analyze"]
    assert get("path=data/raw.csv")["input_to_stages"] == ["sweep", "analyze"]
    assert get("path=data/downloaded/a.csv")["input_to_stages"] == [
        "summarize"
    ]
    assert get("path=results/metrics.json")["input_to_stages"] == []
