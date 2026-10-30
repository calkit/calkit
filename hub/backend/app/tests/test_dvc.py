"""Tests for the ``dvc`` module."""

import os
from copy import deepcopy
from pathlib import Path

import pytest

from app.dvc import (
    get_data_fpath_for_md5,
    make_mermaid_diagram,
    output_from_pipeline,
    run_dvc_command,
)


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


def test_make_mermaid_diagram(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dvc.exceptions import OutputDuplicationError
    from dvc.parsing import ResolveError

    # Run from a directory away from the root, where DVC's paths relative
    # to the working directory would show up in labels
    wdir = tmp_path / "a" / "b"
    wdir.mkdir(parents=True)
    monkeypatch.chdir(wdir)
    pipeline = {
        "stages": {
            "do-something": {
                "cmd": "echo sup",
                "deps": ["somefile.py"],
                "outs": ["something.png"],
            },
            "do-something-else": {
                "cmd": "echo ${lr}",
                "deps": ["something.png"],
                "outs": ["else.pdf"],
            },
            "loop": {
                "foreach": [1, 2],
                "do": {
                    "cmd": "echo ${item}",
                    "deps": ["else.pdf"],
                    "outs": ["out-${item}.txt"],
                },
            },
        }
    }
    mm = make_mermaid_diagram(pipeline, params={"lr": 0.1})
    assert mm == (
        "flowchart TD"
        '\n\tnode1["do-something"]'
        '\n\tnode2["do-something-else"]'
        '\n\tnode3["loop@1"]'
        '\n\tnode4["loop@2"]'
        "\n\tnode1-->node2"
        "\n\tnode2-->node3"
        "\n\tnode2-->node4"
    )
    # Neither the working directory nor its contents change
    assert os.getcwd() == str(wdir)
    assert os.listdir(wdir) == []
    # Errors name stages, not their paths relative to the working directory
    with pytest.raises(OutputDuplicationError) as exc_info:
        make_mermaid_diagram(
            {
                "stages": {
                    "a": {"cmd": "x", "outs": ["o"]},
                    "b": {"cmd": "y", "outs": ["o"]},
                }
            }
        )
    assert "\t- a\n" in str(exc_info.value)
    assert "dvc.yaml" not in str(exc_info.value)
    # A missing param still fails
    with pytest.raises(ResolveError, match="Could not find 'lr'"):
        make_mermaid_diagram(pipeline)
    # Stage names come from the repo, so they can't add Mermaid of their own,
    # e.g., a click with a javascript: link
    name = 'x"]\n\tclick node1 href "javascript:alert(1)"\n\tnode9["`<b>`'
    mm = make_mermaid_diagram(
        {
            "stages": {
                name: {"cmd": "echo", "outs": ["o"]},
                "b": {"cmd": "echo", "deps": ["o"]},
            }
        }
    )
    lines = mm.splitlines()
    assert lines[0] == "flowchart TD"
    assert lines[1] == '\tnode1["b"]'
    assert lines[2].startswith('\tnode2["x#34;#93;#10;#9;click node1 href')
    assert lines[2].endswith('#96;#60;b#62;#96;"]')
    assert lines[3:] == ["\tnode2-->node1"]
    for c in '"[]`<>\n':
        assert c not in lines[2][len('\tnode2["') : -len('"]')]


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


def test_get_data_fpath_for_md5_takes_only_hashes():
    class FakeFs:
        def __init__(self):
            self.looked_up: list[str] = []

        def isfile(self, path):
            self.looked_up.append(path)
            return True

        exists = isfile

    fs = FakeFs()
    md5 = "0123456789abcdef0123456789abcdef"
    for valid in (md5, md5 + ".dir"):
        path = get_data_fpath_for_md5("me", "proj", valid, fs=fs)
        assert path is not None and path.endswith(valid[2:])
    # The hash comes from the project's own files, so anything that isn't
    # one never makes it into a storage path
    fs.looked_up.clear()
    crafted = [
        "ab/../../../them/their-proj/files/md5/01/23456789",
        "../" + md5,
        md5 + "/..",
        md5.upper(),
        "abc",
        "",
    ]
    for bad in crafted:
        assert get_data_fpath_for_md5("me", "proj", bad, fs=fs) is None
    assert fs.looked_up == []
