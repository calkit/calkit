import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

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
    }
    tree = SimpleNamespace(
        is_file=lambda path: path in files,
        is_dir=lambda path: False,
    )
    ck_info = {
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
            }
        }
    }
    pipeline = PipelineAtRef(
        dvc_yaml={},
        dvc_lock={
            "stages": {
                "analyze": {
                    "deps": [
                        {"path": "scripts/analyze.py"},
                        {"path": "data/raw.csv"},
                        {"path": ".calkit/env-locks/py.json"},
                    ],
                    "outs": [{"path": "results/metrics.json"}],
                }
            }
        },
        statuses={"analyze": PipelineStageStatus(status="stale")},
        frozen=set(),
    )

    def contents(project, repo, path, ref):
        return SimpleNamespace(content=base64.b64encode(files[path].encode()))

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
                f"{MODULE}.app.projects.get_contents_from_repo",
                side_effect=contents,
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
    # A stage never run is still found from calkit.yaml, relative to its
    # wdir, though nothing has produced the file yet
    body = get("path=figs/out.png")
    assert not body["exists"]
    assert body["stage"] == "plot"
    assert body["source"] == "figs/plot.py"
    assert body["stage_status"] is None
    # Nothing produces an authored file
    body = get("path=scripts/analyze.py")
    assert body["exists"]
    assert body["stage"] is None
    # and it isn't a results file, so there's no value to read
    assert body["value"] is None
    assert body["value_error"] is None
