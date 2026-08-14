"""Tests for the ``dvc`` module."""

import os
from copy import deepcopy

from app.dvc import make_mermaid_diagram, output_from_pipeline, run_dvc_command


def test_ck_remote_scheme_is_registered(tmp_path):
    """New projects get a ck:// DVC remote, so both the in-process schema and
    the DVC CLI we shell out to must accept one.

    DVC memoizes its compiled config schema the first time any config is read,
    which is why importing ``app.dvc`` registers the scheme.
    """
    from dvc.config import get_compiled_schema

    make_mermaid_diagram({"stages": {"a": {"cmd": "echo hi", "outs": ["x"]}}})
    get_compiled_schema()({"remote": {"calkit": {"url": "ck://owner/proj"}}})
    wdir = str(tmp_path)
    assert run_dvc_command(["init", "--no-scm", "-q"], wdir=wdir) == 0
    assert (
        run_dvc_command(
            ["remote", "add", "-d", "-f", "calkit", "ck://owner/proj"],
            wdir=wdir,
        )
        == 0
    )
    assert run_dvc_command(["status"], wdir=wdir) == 0


def test_make_mermaid_diagram():
    pipeline = {
        "stages": {
            "do-something": {
                "cmd": "echo sup",
                "deps": ["somefile.py"],
                "outs": ["something.png"],
            },
            "do-something-else": {
                "cmd": "echo sup2",
                "deps": ["something.png"],
                "outs": ["else.pdf"],
            },
        }
    }
    mm = make_mermaid_diagram(pipeline)
    return mm


def test_output_from_pipeline():
    print(os.getcwd())
    pipeline = {
        "stages": {
            "my_stage": {"deps": []},
            "subdir_stage": {
                "wdir": "backend/scripts",
            },
        }
    }
    lock = deepcopy(pipeline)
    lock["stages"]["my_stage"]["outs"] = [
        {
            "path": "README.md",
            "hash": "md5",
            "md5": "0ac9de94eb7bc991d60df6d4d8a7553d",
            "size": 2828,
        }
    ]
    lock["stages"]["subdir_stage"]["outs"] = [
        {
            "path": "create-initial-data.py",
            "hash": "md5",
            "md5": "0ac9de94eb7bc991d60df6d4d8a7553c",
            "size": 282843,
        }
    ]
    out = output_from_pipeline(
        "README.md", "my_stage", pipeline=pipeline, lock=lock
    )
    assert isinstance(out, dict)
    assert out["path"] == "README.md"
    out = output_from_pipeline(
        "backend/scripts/create-initial-data.py",
        "subdir_stage",
        pipeline=pipeline,
        lock=lock,
    )
    assert isinstance(out, dict)
    assert out["path"] == "backend/scripts/create-initial-data.py"
    assert out["md5"].endswith("3c")
    out = output_from_pipeline(
        "something-that-wont/exist",
        "subdir_stage",
        pipeline=pipeline,
        lock=lock,
    )
    assert out is not None
    # Now check that out will be None if we have multiple outs
    lock["stages"]["subdir_stage"]["outs"].append(
        {
            "path": "create-initial-data-2.py",
            "hash": "md5",
            "md5": "0ac9de94eb7bc991d60df6d4d8a7553c",
            "size": 282843,
        }
    )
    out = output_from_pipeline(
        "something-that-wont/exist",
        "subdir_stage",
        pipeline=pipeline,
        lock=lock,
    )
    assert out is None


def test_expand_dvc_lock_outs():
    """This requires the `petebachant/snakemake-tutorial` project to be
    populated in the dev environment.
    """
    pass  # TODO
