import os
import subprocess
import sys
import zipfile

from typer.testing import CliRunner

import calkit
from calkit.cli.main.core import app

runner = CliRunner()


def test_release_with_pipeline(tmp_dir):
    ck_info = {
        "title": "Test Project",
        "description": "Test",
        "environments": {
            "used": {"kind": "uv-venv", "path": "requirements.txt"},
            "unused": {"kind": "uv-venv", "path": "other-requirements.txt"},
        },
        "publications": [
            {
                "path": "out2.txt",
                "kind": "journal-article",
                "title": "Test Publication",
            }
        ],
        "pipeline": {
            "stages": {
                "upstream": {
                    "kind": "command",
                    "command": "echo '1' > out1.txt",
                    "environment": "_system",
                    "outputs": ["out1.txt"],
                },
                "target": {
                    "kind": "command",
                    "command": "cat out1.txt > out2.txt",
                    "environment": "used",
                    "inputs": ["out1.txt"],
                    "outputs": ["out2.txt"],
                },
                "unrelated": {
                    "kind": "command",
                    "command": "echo '3' > out3.txt",
                    "environment": "unused",
                    "outputs": ["out3.txt"],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("requirements.txt", "w") as f:
        f.write("")
    with open("other-requirements.txt", "w") as f:
        f.write("")
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["git", "config", "user.email", "test@test.com"])
    subprocess.check_call(["git", "config", "user.name", "Test"])
    subprocess.check_call(["dvc", "init"])
    subprocess.check_call(["dvc", "config", "core.analytics", "false"])
    with open("dvc.yaml", "w") as f:
        calkit.ryaml.dump(
            {"stages": calkit.pipeline.to_dvc(ck_info=ck_info)}, f
        )
    # Run through calkit rather than DVC directly so the environments get
    # built and locked, which the generated stages depend on
    subprocess.check_call([sys.executable, "-m", "calkit", "run"])
    subprocess.check_call(["git", "add", "."])
    subprocess.check_call(["git", "commit", "-m", "init"])

    class MockStatus:
        errors = []
        failed_environment_checks = []
        stale_stage_names = []
        is_stale = False

    original_get_status = calkit.pipeline.get_status
    original_check = calkit.releases.check_project_release_archive
    calkit.pipeline.get_status = lambda *args, **kwargs: MockStatus()
    checked = []
    calkit.releases.check_project_release_archive = lambda zip_path, **kwargs: (
        checked.append(zip_path)
    )
    try:
        # Without --pipeline, a single-file release stores just that file
        res = runner.invoke(
            app,
            [
                "new",
                "release",
                "-n",
                "plain",
                "--internal",
                "--no-push",
                "out2.txt",
            ],
        )
        assert res.exit_code == 0, res.stdout
        stored = os.listdir(".calkit/releases/plain")
        assert any(f.endswith(".txt") for f in stored)
        assert not any(f.endswith(".zip") for f in stored)
        assert not checked
        # With --pipeline, it becomes an archive holding the artifact plus
        # what builds it, and the archive gets run before being released
        res = runner.invoke(
            app,
            [
                "new",
                "release",
                "-n",
                "v1",
                "--internal",
                "--no-push",
                "--pipeline",
                "out2.txt",
            ],
        )
        assert res.exit_code == 0, res.stdout
        zip_names = [
            f for f in os.listdir(".calkit/releases/v1") if f.endswith(".zip")
        ]
        assert len(zip_names) == 1
        zip_path = os.path.join(".calkit/releases/v1", zip_names[0])
        assert checked == [zip_path]
        # --pipeline on a project release is redundant, not an error
        res = runner.invoke(
            app,
            [
                "new",
                "release",
                "-n",
                "v2",
                "--internal",
                "--no-push",
                "--dry-run",
                "--pipeline",
                ".",
            ],
        )
        assert res.exit_code == 0, res.stdout
        assert "already include the pipeline" in res.stdout
    finally:
        calkit.pipeline.get_status = original_get_status
        calkit.releases.check_project_release_archive = original_check

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        assert "calkit.yaml" in names
        assert "dvc.yaml" in names
        assert "dvc.lock" in names
        assert "requirements.txt" in names
        # The target and its upstream are needed to rebuild it
        assert "out1.txt" in names
        assert "out2.txt" in names
        # The unrelated stage's output and environment are not
        assert "out3.txt" not in names
        assert "other-requirements.txt" not in names
        dvc_yaml = calkit.ryaml.load(z.read("dvc.yaml").decode())
        assert set(dvc_yaml["stages"]) == {"upstream", "target"}
        dvc_lock = calkit.ryaml.load(z.read("dvc.lock").decode())
        assert set(dvc_lock["stages"]) == {"upstream", "target"}
        ck_yaml = calkit.ryaml.load(z.read("calkit.yaml").decode())
        assert set(ck_yaml["pipeline"]["stages"]) == {"upstream", "target"}
        assert set(ck_yaml["environments"]) == {"used"}
        # The release record notes that it carries its own pipeline
        assert ck_yaml["releases"]["plain"]["includes_pipeline"] is False
        # The archive says what produced it, naming the Git tag to get back
        # to, without disturbing the project's own README
        note = z.read("CALKIT-RELEASE.md").decode()
        assert f"Calkit v{calkit.__version__}" in note
        assert "Git tag v1" in note
        assert "README.md" not in names or z.read("README.md") != note


def test_release_detached_head(tmp_dir):
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"title": "Test", "description": "Test"}, f)
    with open("out.txt", "w") as f:
        f.write("hi\n")
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["git", "config", "user.email", "test@test.com"])
    subprocess.check_call(["git", "config", "user.name", "Test"])
    subprocess.check_call(["dvc", "init"])
    subprocess.check_call(["dvc", "config", "core.analytics", "false"])
    subprocess.check_call(["git", "add", "."])
    subprocess.check_call(["git", "commit", "-m", "init"])
    subprocess.check_call(["git", "checkout", "--detach", "HEAD"])
    # A release that would push has no branch to push from, and says so
    # before anything gets uploaded
    res = runner.invoke(
        app,
        ["new", "release", "-n", "v1", "--internal", "--kind", "dataset", "."],
    )
    assert res.exit_code != 0
    assert "HEAD is detached" in res.stdout + str(res.stderr)
    # Nothing was written for the release before bailing out
    assert not os.path.exists(".calkit/releases/v1")
    # Skipping the commit means there's nothing to push, so it goes ahead
    res = runner.invoke(
        app,
        [
            "new",
            "release",
            "-n",
            "v1",
            "--internal",
            "--kind",
            "dataset",
            "--no-commit",
            ".",
        ],
    )
    assert res.exit_code == 0, res.stdout
