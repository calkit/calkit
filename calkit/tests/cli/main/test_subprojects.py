"""Integration tests for subproject support."""

import os
import subprocess

import calkit
import calkit.pipeline


def _ck(path, data):
    """Write a calkit.yaml at ``path``."""
    with open(path, "w") as f:
        calkit.ryaml.dump(data, f)


def _stage(cmd, inputs=None, outputs=None):
    """Build a minimal ``_system`` shell-command stage definition."""
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
    """Inline subproject (no .dvc/) shares the parent DVC project.

    Covers:
    - to_dvc writes sub1/dvc.yaml and includes sub1 stages in parent graph
    - full pipeline run produces expected outputs
    - cross-subproject dependency: parent stage depends on sub1 output
    - stale detection when sub1 input changes
    - target shorthands: ``sub1`` and ``sub1:stage-name``
    """
    subprocess.check_call(["calkit", "init"])
    # --- sub1 setup ---
    os.makedirs("sub1")
    _ck(
        "sub1/calkit.yaml",
        {
            "pipeline": {
                "stages": {
                    "produce": _stage(
                        'echo "from sub1" > a.txt',
                        outputs=[{"path": "a.txt", "storage": "git"}],
                    ),
                    "derive": _stage(
                        "cat a.txt > b.txt",
                        inputs=["a.txt"],
                        outputs=[{"path": "b.txt", "storage": "git"}],
                    ),
                }
            }
        },
    )
    # --- parent setup ---
    _ck(
        "calkit.yaml",
        {
            "subprojects": [{"path": "sub1"}],
            "pipeline": {
                "stages": {
                    "consume": _stage(
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
    _ck("sub1/calkit.yaml", ck_sub1)
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
    _ck("sub1/calkit.yaml", ck_sub1)
    calkit.pipeline.to_dvc(write=True, manage_gitignore=False)
    subprocess.check_call(["calkit", "run", "sub1:produce"])
    with open("sub1/a.txt") as f:
        assert "v2" in f.read()


# ---------------------------------------------------------------------------
# Isolated subproject
# ---------------------------------------------------------------------------


def _init_isolated_subproject(path, stages):
    """Create a directory with its own git + dvc + calkit project."""
    os.makedirs(path, exist_ok=True)
    subprocess.check_call(["git", "init"], cwd=path)
    subprocess.check_call(
        ["git", "config", "user.email", "test@test.com"], cwd=path
    )
    subprocess.check_call(["git", "config", "user.name", "Test"], cwd=path)
    subprocess.check_call(["dvc", "init"], cwd=path)
    _ck(
        os.path.join(path, "calkit.yaml"),
        {"pipeline": {"stages": stages}},
    )
    calkit.pipeline.to_dvc(wdir=path, write=True, manage_gitignore=False)


def test_isolated_subproject(tmp_dir):
    """Isolated subproject (has .dvc/) gets a wrapper stage in parent dvc.yaml.

    Covers:
    - to_dvc generates ``_subproject-<name>`` wrapper stage
    - wrapper deps/outs capture the I/O boundary
    - full run executes wrapper which calls ``calkit dvc repro`` inside sub2
    - status display uses ``sub2 (subproject)`` label when wrapper is stale
    - target ``sub2`` maps to the wrapper stage
    - target ``sub2:stage`` runs dvc repro <stage> inside sub2
    """
    subprocess.check_call(["calkit", "init"])
    # --- isolated sub2 ---
    _init_isolated_subproject(
        "sub2",
        {
            "make-file": _stage(
                'echo "hello from sub2" > out.txt',
                outputs=[{"path": "out.txt", "storage": "git"}],
            ),
            "derive": _stage(
                "cat out.txt > derived.txt",
                inputs=["out.txt"],
                outputs=[{"path": "derived.txt", "storage": "git"}],
            ),
        },
    )
    # --- parent setup ---
    _ck(
        "calkit.yaml",
        {
            "subprojects": [{"path": "sub2"}],
            "pipeline": {
                "stages": {
                    "consume": _stage(
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
    # Wrapper stage displayed as ``sub2 (subproject)`` or
    # expanded sub2 stage names
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
    # --- target shorthand: ck run sub2 → wrapper stage ---
    # Remove sub2's output to make the wrapper stale, then re-run via shorthand.
    os.remove("sub2/out.txt")
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
