import pytest
import os
import calkit
from typer.testing import CliRunner
from calkit.cli.main.core import app
import subprocess

runner = CliRunner()

def test_release_create_target(tmp_dir):
    ck_info = {
        "pipeline": {
            "stages": {
                "s1": {
                    "kind": "command",
                    "command": "echo '1' > out1.txt",
                    "environment": "_system",
                    "outputs": ["out1.txt"]
                },
                "s2": {
                    "kind": "command",
                    "command": "echo '2' > out2.txt",
                    "environment": "_system",
                    "outputs": ["out2.txt"]
                }
            }
        },
        "title": "Test Project",
        "description": "Test"
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
        
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["git", "config", "user.email", "test@test.com"])
    subprocess.check_call(["git", "config", "user.name", "Test"])
    subprocess.check_call(["git", "add", "calkit.yaml"])
    subprocess.check_call(["git", "commit", "-m", "init"])
    subprocess.check_call(["dvc", "init"])
    
    with open("dvc.yaml", "w") as f:
        dvc_yaml = {"stages": calkit.pipeline.to_dvc(ck_info=ck_info)}
        calkit.ryaml.dump(dvc_yaml, f)
    subprocess.check_call(["dvc", "config", "core.analytics", "false"])
    subprocess.check_call(["dvc", "repro"])
    
    subprocess.check_call(["git", "add", "."])
    subprocess.check_call(["git", "commit", "-m", "repro"])

    class MockStatus:
        errors = []
        failed_environment_checks = []
        stale_stage_names = []
        is_stale = False
        
    original_get_status = calkit.pipeline.get_status
    calkit.pipeline.get_status = lambda *args, **kwargs: MockStatus()
    
    res = runner.invoke(app, ["new", "release", "-n", "v1", "--target", "s1", "--internal", "--no-push"])
    calkit.pipeline.get_status = original_get_status
    if res.exception:
        import traceback
        traceback.print_exception(type(res.exception), res.exception, res.exception.__traceback__)
    assert res.exit_code == 0, res.stdout
    
    zip_files = os.listdir(".calkit/releases/v1")
    assert any(f.endswith(".zip") for f in zip_files)
    
    import zipfile
    zip_path = os.path.join(".calkit/releases/v1", zip_files[0])
    with zipfile.ZipFile(zip_path, "r") as z:
        names = z.namelist()
        assert "calkit.yaml" in names
        assert "dvc.yaml" in names
        assert "out1.txt" in names
        # out2.txt should NOT be in the release because it's not needed by s1!
        assert "out2.txt" not in names
        
        dvc_yaml_str = z.read("dvc.yaml").decode()
        dvc_yaml = calkit.ryaml.load(dvc_yaml_str)
        assert "s1" in dvc_yaml["stages"]
        assert "s2" not in dvc_yaml["stages"]
        
        ck_yaml_str = z.read("calkit.yaml").decode()
        ck_yaml = calkit.ryaml.load(ck_yaml_str)
        assert "s1" in ck_yaml["pipeline"]["stages"]
        assert "s2" not in ck_yaml["pipeline"]["stages"]
