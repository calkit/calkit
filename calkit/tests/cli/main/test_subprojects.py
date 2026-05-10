"""Integration tests for subproject support."""

import os
import subprocess

import calkit
import calkit.pipeline


def write_ck_info(path, data):
    with open(path, "w") as f:
        calkit.ryaml.dump(data, f)


def make_stage(cmd, inputs=None, outputs=None):
    s = {"kind": "command", "environment": "_system", "command": cmd}
    if inputs:
        s["inputs"] = inputs
    if outputs:
        s["outputs"] = outputs
    return s


# ---------------------------------------------------------------------------
# Inline subproject
# ---------------------------------------------------------------------------


def test_inline_subproject(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # --- sub1 setup ---
    os.makedirs("sub1")
    write_ck_info(
        "sub1/calkit.yaml",
        {
            "pipeline": {
                "stages": {
                    "produce": make_stage(
                        'echo "from sub1" > a.txt',
                        outputs=[{"path": "a.txt", "storage": "git"}],
                    ),
                    "derive": make_stage(
                        "cat a.txt > b.txt",
                        inputs=["a.txt"],
                        outputs=[{"path": "b.txt", "storage": "git"}],
                    ),
                }
            }
        },
    )
    # --- parent setup ---
    write_ck_info(
        "calkit.yaml",
        {
            "subprojects": [{"path": "sub1"}],
            "pipeline": {
                "stages": {
                    "consume": make_stage(
                        "cat sub1/a.txt > merged.txt",
                        inputs=["sub1/a.txt"],
                        outputs=[{"path": "merged.txt", "storage": "git"}],
                    )
                }
            },
        },
    )
    # DVC pipeline compilation should produce sub1/dvc.yaml and root dvc.yaml
    calkit.pipeline.to_dvc(write=True, manage_gitignore=False)
    assert os.path.isfile("sub1/dvc.yaml")
    with open("sub1/dvc.yaml") as f:
        sub1_dvc = calkit.ryaml.load(f)
    assert "produce" in sub1_dvc["stages"]
    assert "derive" in sub1_dvc["stages"]
    with open("dvc.yaml") as f:
        root_dvc = calkit.ryaml.load(f)
    # No wrapper stage for inline subprojects
    assert "_subproject-sub1" not in root_dvc.get("stages", {})
    assert "consume" in root_dvc["stages"]
    # --- full run ---
    subprocess.check_call(["calkit", "run"])
    assert os.path.isfile("sub1/a.txt")
    assert os.path.isfile("sub1/b.txt")
    assert os.path.isfile("merged.txt")
    with open("merged.txt") as f:
        assert "from sub1" in f.read()
    # --- pipeline should be up to date ---
    status = calkit.pipeline.get_status(
        check_environments=False, compile_to_dvc=False
    )
    assert not status.is_stale
    # --- stale detection: change sub1's upstream command ---
    ck_sub1 = calkit.load_calkit_info(wdir="sub1")
    ck_sub1["pipeline"]["stages"]["produce"]["command"] = (
        'echo "updated" > a.txt'
    )
    write_ck_info("sub1/calkit.yaml", ck_sub1)
    calkit.pipeline.to_dvc(write=True, manage_gitignore=False)
    status = calkit.pipeline.get_status(
        check_environments=False, compile_to_dvc=False
    )
    assert status.is_stale
    stale_names = set(status.stale_stage_names)
    # sub1 produce is stale due to changed command; derive + consume downstream
    assert any("produce" in n for n in stale_names)
    # --- target shorthand: run just sub1 ---
    subprocess.check_call(["calkit", "run", "sub1"])
    assert os.path.isfile("sub1/a.txt")
    with open("sub1/a.txt") as f:
        assert "updated" in f.read()
    # merged.txt should still have old content (parent not yet re-run)
    with open("merged.txt") as f:
        assert "from sub1" in f.read()
    # --- target shorthand: run a specific sub1 stage ---
    # Reset to make produce stale again
    ck_sub1["pipeline"]["stages"]["produce"]["command"] = 'echo "v2" > a.txt'
    write_ck_info("sub1/calkit.yaml", ck_sub1)
    calkit.pipeline.to_dvc(write=True, manage_gitignore=False)
    subprocess.check_call(["calkit", "run", "sub1:produce"])
    with open("sub1/a.txt") as f:
        assert "v2" in f.read()


# ---------------------------------------------------------------------------
# Isolated subproject
# ---------------------------------------------------------------------------


def _init_isolated_subproject(path, stages):
    os.makedirs(path, exist_ok=True)
    subprocess.check_call(["git", "init"], cwd=path)
    subprocess.check_call(
        ["git", "config", "user.email", "test@test.com"], cwd=path
    )
    subprocess.check_call(["git", "config", "user.name", "Test"], cwd=path)
    subprocess.check_call(["dvc", "init"], cwd=path)
    write_ck_info(
        os.path.join(path, "calkit.yaml"),
        {"pipeline": {"stages": stages}},
    )
    calkit.pipeline.to_dvc(wdir=path, write=True, manage_gitignore=False)


def test_isolated_subproject(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # --- isolated sub2 ---
    _init_isolated_subproject(
        "sub2",
        {
            "make-file": make_stage(
                'echo "hello from sub2" > out.txt',
                outputs=[{"path": "out.txt", "storage": "git"}],
            ),
            "derive": make_stage(
                "cat out.txt > derived.txt",
                inputs=["out.txt"],
                outputs=[{"path": "derived.txt", "storage": "git"}],
            ),
        },
    )
    # --- parent setup ---
    write_ck_info(
        "calkit.yaml",
        {
            "subprojects": [{"path": "sub2"}],
            "pipeline": {
                "stages": {
                    "consume": make_stage(
                        "cat sub2/out.txt > parent.txt",
                        inputs=["sub2/out.txt"],
                        outputs=[{"path": "parent.txt", "storage": "git"}],
                    )
                }
            },
        },
    )
    # --- wrapper stage generation ---
    calkit.pipeline.to_dvc(write=True, manage_gitignore=False)
    with open("dvc.yaml") as f:
        root_dvc = calkit.ryaml.load(f)
    assert "_subproject-sub2" in root_dvc["stages"]
    wrapper = root_dvc["stages"]["_subproject-sub2"]
    assert wrapper["cmd"] == "calkit dvc repro"
    assert wrapper["wdir"] == "sub2"
    # out.txt must appear in wrapper outs (as cache:false, persist:true)
    wrapper_out_paths = [
        list(o.keys())[0] if isinstance(o, dict) else o
        for o in wrapper["outs"]
    ]
    assert "out.txt" in wrapper_out_paths
    assert "derived.txt" in wrapper_out_paths
    # --- initial status: all stages stale ---
    status = calkit.pipeline.get_status(
        check_environments=False, compile_to_dvc=False
    )
    assert status.is_stale
    stale_names = set(status.stale_stage_names)
    # Wrapper stage displayed as ``sub2 (subproject)`` or expanded sub2 stage names
    assert any("sub2" in n for n in stale_names)
    # --- full run via parent ---
    subprocess.check_call(["calkit", "run"])
    assert os.path.isfile("sub2/out.txt")
    assert os.path.isfile("sub2/derived.txt")
    assert os.path.isfile("parent.txt")
    with open("parent.txt") as f:
        assert "hello from sub2" in f.read()
    # --- after full run, pipeline is up to date ---
    status = calkit.pipeline.get_status(
        check_environments=False, compile_to_dvc=False
    )
    assert not status.is_stale
    # --- stale paths must be parent-relative ---
    # Removing sub2/out.txt makes sub2 stale again.
    os.remove("sub2/out.txt")
    status = calkit.pipeline.get_status(
        check_environments=False, compile_to_dvc=False
    )
    assert status.is_stale
    for stage_name, stage_info in status.stale_stages.items():
        if "sub2" not in stage_name:
            continue
        for path in stage_info.stale_outputs + stage_info.modified_inputs:
            # All paths must be parent-relative (start with "sub2/")
            assert path.startswith("sub2/") or path.startswith(
                "sub2"
            ), f"Path '{path}' in stage '{stage_name}' is not parent-relative"
    # --- target shorthand: ck run sub2 → wrapper stage ---
    # out.txt was removed above; re-run via shorthand.
    subprocess.check_call(["calkit", "run", "sub2"])
    assert os.path.isfile("sub2/out.txt")
    with open("sub2/out.txt") as f:
        assert "hello from sub2" in f.read()
    # parent.txt should not have been re-run (we only targeted sub2)
    with open("parent.txt") as f:
        assert "hello from sub2" in f.read()
    # --- target shorthand: ck run sub2:stage → runs inside sub2 ---
    # Remove sub2's output again to make the specific stage stale.
    os.remove("sub2/out.txt")
    subprocess.check_call(["calkit", "run", "sub2:make-file"])
    assert os.path.isfile("sub2/out.txt")
    with open("sub2/out.txt") as f:
        assert "hello from sub2" in f.read()


# ---------------------------------------------------------------------------
# Cross-subproject external dependency (MDOcean / OpenFLASH pattern)
# ---------------------------------------------------------------------------


def test_isolated_subproject_external_dep(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # The parent produces shared.txt which the isolated subproject reads.
    _init_isolated_subproject(
        "solver",
        {
            "solve": make_stage(
                "cat ../shared.txt > solution.txt",
                inputs=["../shared.txt"],
                outputs=[{"path": "solution.txt", "storage": "git"}],
            ),
        },
    )
    write_ck_info(
        "calkit.yaml",
        {
            "subprojects": [{"path": "solver"}],
            "pipeline": {
                "stages": {
                    "make-shared": make_stage(
                        'echo "mesh data" > shared.txt',
                        outputs=[{"path": "shared.txt", "storage": "git"}],
                    ),
                    "post-process": make_stage(
                        "cat solver/solution.txt > final.txt",
                        inputs=["solver/solution.txt"],
                        outputs=[{"path": "final.txt", "storage": "git"}],
                    ),
                }
            },
        },
    )
    # Compile and verify wrapper structure
    calkit.pipeline.to_dvc(write=True, manage_gitignore=False)
    with open("dvc.yaml") as f:
        root_dvc = calkit.ryaml.load(f)
    wrapper = root_dvc["stages"]["_subproject-solver"]
    wrapper_dep_set = set(wrapper.get("deps", []))
    wrapper_out_paths = {
        list(o.keys())[0] if isinstance(o, dict) else o
        for o in wrapper.get("outs", [])
    }
    # shared.txt (via ../shared.txt relative to solver/) must be a dep only
    assert "../shared.txt" in wrapper_dep_set
    assert "../shared.txt" not in wrapper_out_paths
    assert not wrapper_dep_set & wrapper_out_paths, "wrapper dep/out overlap"
    # Full run must produce all outputs
    subprocess.check_call(["calkit", "run"])
    assert os.path.isfile("shared.txt")
    assert os.path.isfile("solver/solution.txt")
    assert os.path.isfile("final.txt")
    with open("final.txt") as f:
        assert "mesh data" in f.read()
    # After run, pipeline should be up to date
    status = calkit.pipeline.get_status(
        check_environments=False, compile_to_dvc=False
    )
    assert not status.is_stale
