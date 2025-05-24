"""Tests for ``calkit.models.pipeline``."""

from calkit.models.pipeline import PythonScriptStage


def test_pythonscriptstage():
    s = PythonScriptStage.model_validate(
        dict(
            kind="python-script",
            script_path="scripts/my-script.py",
            environment="py1",
            inputs=["data/raw.csv"],
            outputs=[
                "data/processed.csv",
                dict(path="data/something.csv", storage="git"),
            ],
        )
    )
    sd = s.to_dvc()
    assert sd["cmd"] == "calkit xenv -n py1 -- python scripts/my-script.py"
