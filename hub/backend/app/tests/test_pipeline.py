"""Tests for app.pipeline (pipeline staleness detection)."""

import hashlib

import git

from app.git import get_repo_tree_for_ref
from app.pipeline import (
    _precompute_storage_presence,
    calc_overall_pipeline_status,
    compute_stage_statuses,
    find_stage_for_path,
)


class FakeFS:
    """Minimal fsspec-like FS recording which md5s exist in object storage.

    Implements both access patterns the presence check uses: `find` for the
    listing path it normally takes, and `exists` for the per-md5 fallback.
    `find_error` forces the fallback.
    """

    def __init__(
        self,
        existing_md5s: set[str] | None = None,
        find_error: Exception | None = None,
    ) -> None:
        self._existing = existing_md5s or set()
        self._find_error = find_error
        self.find_calls = 0
        self.exists_calls = 0

    def exists(self, path: str) -> bool:
        self.exists_calls += 1
        return any(
            md5[:2] in path and md5[2:] in path for md5 in self._existing
        )

    def find(self, path: str) -> list[str]:
        self.find_calls += 1
        if self._find_error is not None:
            raise self._find_error
        # Both layouts put objects at <prefix>/<idx>/<rest>.
        return [f"{path}/{md5[:2]}/{md5[2:]}" for md5 in self._existing]


def _init_repo(repo_dir) -> git.Repo:
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    return repo


def _commit(repo: git.Repo, files: dict[str, str], msg: str) -> None:
    root = repo.working_dir
    paths = []
    for rel, content in files.items():
        full = f"{root}/{rel}"
        import os

        os.makedirs(os.path.dirname(full) or root, exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        paths.append(rel)
    repo.git.add(paths)
    repo.git.commit(["-m", msg])


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def test_up_to_date_stage(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    script = "print('hi')\n"
    _commit(
        repo,
        {"script.py": script, "out.txt": "result\n"},
        "init",
    )
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["out.txt"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5(script)}],
                "outs": [{"path": "out.txt", "md5": _md5("result\n")}],
            }
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "up-to-date"
    assert calc_overall_pipeline_status(statuses) == "up-to-date"


def test_modified_command(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    script = "print('hi')\n"
    _commit(
        repo,
        {"script.py": script, "out.txt": "result\n"},
        "init",
    )
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py --new",
                "deps": ["script.py"],
                "outs": ["out.txt"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5(script)}],
                "outs": [{"path": "out.txt", "md5": _md5("result\n")}],
            }
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "stale"
    assert statuses["run"].modified_command is True


def test_modified_input(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(
        repo,
        {"script.py": "print('new')\n", "out.txt": "result\n"},
        "init",
    )
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["out.txt"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5("print('old')\n")}],
                "outs": [{"path": "out.txt", "md5": _md5("result\n")}],
            }
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "stale"
    assert "script.py" in statuses["run"].modified_inputs


def test_missing_output_found_in_object_storage(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"script.py": "x\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    out_md5 = _md5("result\n")
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["data/out.bin"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5("x\n")}],
                "outs": [{"path": "data/out.bin", "md5": out_md5}],
            }
        }
    }
    fs = FakeFS(existing_md5s={out_md5})
    statuses = compute_stage_statuses(dvc_yaml, dvc_lock, tree, "o", "p", fs)
    assert statuses["run"].status == "up-to-date"


def test_missing_output_not_in_object_storage(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"script.py": "x\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["data/out.bin"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5("x\n")}],
                "outs": [{"path": "data/out.bin", "md5": _md5("result\n")}],
            }
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "stale"
    assert "data/out.bin" in statuses["run"].missing_outputs


def test_zip_stored_output_is_not_stale(tmp_path):
    """A dvc-zip-stored output lives under .calkit/zip, not files/md5, so the
    standard md5 presence check can't find it. It must not be flagged missing
    when .calkit/zip/paths.json maps it (calkit status sees it up to date).
    """
    import json

    repo = _init_repo(tmp_path / "repo")
    zip_paths = json.dumps({"data/mydir": ".calkit/zip/files/data/mydir.zip"})
    _commit(
        repo,
        {"script.py": "x\n", ".calkit/zip/paths.json": zip_paths},
        "init",
    )
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["data/mydir"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5("x\n")}],
                "outs": [{"path": "data/mydir", "md5": f"{_md5('c')}.dir"}],
            }
        }
    }
    # FakeFS has no objects, so presence is False -- only the zip mapping
    # keeps this from being flagged stale.
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "up-to-date"
    assert not statuses["run"].missing_outputs


def test_cache_false_output_not_flagged_stale(tmp_path):
    """An out declared ``cache: false`` (e.g. calkit map-paths dir-to-dir) is
    never pushed to object storage and is often gitignored, so the hub can't
    observe it. It must not be flagged missing (calkit checks the workspace
    file and reports up to date)."""
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"script.py": "x\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": [{"paper/figures": {"cache": False, "persist": True}}],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5("x\n")}],
                "outs": [{"path": "paper/figures", "md5": f"{_md5('c')}.dir"}],
            }
        }
    }
    # FakeFS has no objects and paper/figures isn't in the tree, so without the
    # cache:false handling this would be wrongly flagged missing/stale.
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "up-to-date"
    assert not statuses["run"].missing_outputs


def test_orphaned_lock_stage_is_ignored(tmp_path):
    """A dvc.lock stage no longer in dvc.yaml (renamed/removed) isn't reported,
    even if its recorded outs would look missing/stale."""
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"script.py": "x\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "keep": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["out.txt"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "keep": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5("x\n")}],
                "outs": [{"path": "out.txt", "md5": _md5("r\n")}],
            },
            "gone": {
                "cmd": "python old.py",
                "deps": [{"path": "old.py", "md5": "old"}],
                "outs": [{"path": "old.bin", "md5": "missing"}],
            },
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS({_md5("r\n")})
    )
    assert "gone" not in statuses
    assert statuses["keep"].status == "up-to-date"


def test_matrix_bare_lock_entry_is_ignored(tmp_path):
    """A matrix stage's bare lock entry is stale cruft; only name@... count."""
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"run.py": "x\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "bench": {
                "matrix": {"n": [1]},
                "cmd": "python run.py ${item.n}",
                "deps": ["run.py"],
                "outs": ["out-${item.n}.txt"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "bench": {  # stale bare entry: missing out would look stale
                "cmd": "python run.py",
                "deps": [{"path": "run.py", "md5": _md5("x\n")}],
                "outs": [{"path": "stale-out.txt", "md5": "missing"}],
            },
            "bench@1": {
                "cmd": "python run.py 1",
                "deps": [{"path": "run.py", "md5": _md5("x\n")}],
                "outs": [{"path": "out-1.txt", "md5": _md5("r\n")}],
            },
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS({_md5("r\n")})
    )
    assert "bench" not in statuses
    assert statuses["bench@1"].status == "up-to-date"


def test_leftover_matrix_expansion_is_ignored(tmp_path):
    """A lock @ entry from an old matrix value (no longer produced by the
    current dvc.yaml matrix) is skipped, even if its objects were gc'd. Only
    the current expansion is reported."""
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"run.py": "x\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "bench": {
                "matrix": {"n": [1]},
                "cmd": "python run.py ${item.n}",
                "deps": ["run.py"],
                "outs": ["out-${item.n}.txt"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "bench@1": {  # current matrix value
                "cmd": "python run.py 1",
                "deps": [{"path": "run.py", "md5": _md5("x\n")}],
                "outs": [{"path": "out-1.txt", "md5": _md5("r\n")}],
            },
            "bench@2": {  # leftover: n=2 no longer in the matrix, object gc'd
                "cmd": "python run.py 2",
                "deps": [{"path": "run.py", "md5": _md5("x\n")}],
                "outs": [{"path": "out-2.txt", "md5": "missing"}],
            },
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS({_md5("r\n")})
    )
    assert statuses["bench@1"].status == "up-to-date"
    assert "bench@2" not in statuses


def test_leftover_matrix_naming_change_is_ignored(tmp_path):
    """When DVC's matrix naming changes (a list-of-dicts matrix names its
    expansions ``@_arg0N``), old ``@v1-v2`` entries linger in the lock with the
    SAME output path. The leftover (old-named) entry must be dropped, not
    flagged stale, even though the current entry's object is present."""
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"run.py": "x\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "bench": {
                "matrix": {"_arg0": [{"a": 1, "b": 3}]},
                "cmd": "run ${item._arg0.a}",
                "deps": ["run.py"],
                "outs": ["out"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "bench@_arg00": {  # current naming, object present
                "cmd": "run 1",
                "deps": [{"path": "run.py", "md5": _md5("x\n")}],
                "outs": [{"path": "out", "md5": _md5("r\n")}],
            },
            "bench@1-3": {  # old naming, same output path, object gc'd
                "cmd": "run 1",
                "deps": [{"path": "run.py", "md5": _md5("x\n")}],
                "outs": [{"path": "out", "md5": "gone"}],
            },
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS({_md5("r\n")})
    )
    assert statuses["bench@_arg00"].status == "up-to-date"
    assert "bench@1-3" not in statuses


def test_committed_dep_beats_stale_producer_out_md5(tmp_path):
    """A dep committed to git uses the committed content, not a producing
    stage's possibly-stale recorded out md5 (e.g. cleaned notebooks)."""
    repo = _init_repo(tmp_path / "repo")
    cleaned = "cleaned-content\n"
    _commit(repo, {"src.py": "x\n", "cleaned.ipynb": cleaned}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "consume": {
                "cmd": "python src.py",
                "deps": ["cleaned.ipynb"],
                "outs": ["out.txt"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "_clean": {  # producer recorded a STALE md5 for cleaned.ipynb
                "cmd": "clean",
                "outs": [{"path": "cleaned.ipynb", "md5": "staleproducermd5"}],
            },
            "consume": {  # dep md5 matches the committed content
                "cmd": "python src.py",
                "deps": [{"path": "cleaned.ipynb", "md5": _md5(cleaned)}],
                "outs": [{"path": "out.txt", "md5": _md5("r\n")}],
            },
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS({_md5("r\n")})
    )
    assert statuses["consume"].status == "up-to-date"
    assert "cleaned.ipynb" not in statuses["consume"].modified_inputs


def test_dead_lock_stage_does_not_resolve_a_dep(tmp_path):
    """A removed stage's leftover out entry doesn't define a dep's current md5.

    dvc.lock keeps entries for stages dropped from dvc.yaml, and one often
    claims the same out path as the stage that replaced it, holding whatever
    md5 it last produced. That entry must not win when resolving a gitignored
    dep's current hash, or every consumer of that path reads a hash nothing
    has produced lately and is reported stale while dvc/calkit call the
    pipeline clean.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"script.py": "x\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    current = _md5("current-data\n")
    dvc_yaml = {
        "stages": {
            "produce": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["data.db"],
            },
            "consume": {
                "cmd": "python script.py",
                "deps": ["data.db"],
                "outs": ["out.txt"],
            },
        }
    }
    dvc_lock = {
        "stages": {
            "produce": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5("x\n")}],
                "outs": [{"path": "data.db", "md5": current}],
            },
            # Renamed away in dvc.yaml, but still in the lock, claiming the
            # same out with the md5 from the last time it ran. It comes after
            # the live producer, so it used to win the outs index.
            "produce-old": {
                "cmd": "python old.py",
                "outs": [{"path": "data.db", "md5": "oldproducermd5"}],
            },
            "consume": {
                "cmd": "python script.py",
                "deps": [{"path": "data.db", "md5": current}],
                "outs": [{"path": "out.txt", "md5": _md5("r\n")}],
            },
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS({current, _md5("r\n")})
    )
    assert "produce-old" not in statuses
    assert statuses["consume"].modified_inputs == []
    assert statuses["consume"].status == "up-to-date"


def test_not_run_stage(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"script.py": "x\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["out.txt"],
            }
        }
    }
    dvc_lock = {"stages": {}}
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "not-run"
    assert calc_overall_pipeline_status(statuses) == "stale"


def test_find_stage_for_path():
    dvc_lock = {
        "stages": {
            "plot": {
                "outs": [{"path": "figures/foo.png", "md5": "abc"}],
            },
            "train": {
                "outs": [{"path": "model.pkl", "md5": "def"}],
            },
        }
    }
    assert find_stage_for_path("figures/foo.png", dvc_lock) == "plot"
    assert find_stage_for_path("model.pkl", dvc_lock) == "train"
    assert find_stage_for_path("missing", dvc_lock) is None


def _simple_pipeline(script: str):
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["out.txt"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5(script)}],
                "outs": [{"path": "out.txt", "md5": _md5("result\n")}],
            }
        }
    }
    return dvc_yaml, dvc_lock


def test_cache_token_short_circuits_recompute(tmp_path):
    """A repeat call with the same token returns the cached result, even when
    the inputs have since changed -- the token, not the lock bytes, governs."""
    repo = _init_repo(tmp_path / "repo")
    script = "print('hi')\n"
    _commit(repo, {"script.py": script, "out.txt": "result\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml, dvc_lock = _simple_pipeline(script)
    token = "tok-shortcircuit"
    first = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS(), cache_token=token
    )
    assert first["run"].status == "up-to-date"
    # A locked dep md5 that no longer matches the tree would be stale on a fresh
    # computation; with the same token the cached up-to-date result is served.
    stale_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": "deadbeef"}],
                "outs": [{"path": "out.txt", "md5": _md5("result\n")}],
            }
        }
    }
    cached = compute_stage_statuses(
        dvc_yaml, stale_lock, tree, "o", "p", FakeFS(), cache_token=token
    )
    assert cached["run"].status == "up-to-date"
    # A different token recomputes and observes the staleness.
    fresh = compute_stage_statuses(
        dvc_yaml, stale_lock, tree, "o", "p", FakeFS(), cache_token="tok-other"
    )
    assert fresh["run"].status == "stale"


def test_unobservable_dep_does_not_make_stage_stale(tmp_path):
    """A dep the hub can't see -- not in git, no .dvc pointer, not another
    stage's out, not in object storage -- must not mark the stage stale. This
    mirrors calkit cleaned notebooks, which are gitignored and cleaned on the
    fly, so they never appear in the pushed repo or remote."""
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, {"out.txt": "result\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "nb": {
                "cmd": "calkit nb execute",
                "deps": [".calkit/notebooks/cleaned/notebook.ipynb"],
                "outs": ["out.txt"],
            }
        }
    }
    dvc_lock = {
        "stages": {
            "nb": {
                "cmd": "calkit nb execute",
                "deps": [
                    {
                        "path": ".calkit/notebooks/cleaned/notebook.ipynb",
                        "md5": "deadbeef",
                    }
                ],
                "outs": [{"path": "out.txt", "md5": _md5("result\n")}],
            }
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["nb"].status == "up-to-date"


def test_always_run_stage_is_not_stale(tmp_path):
    """A stage compiled with always_changed: true (calkit always_run) is not
    stale when that's its only change -- it's surfaced as 'always-run'."""
    repo = _init_repo(tmp_path / "repo")
    script = "print('hi')\n"
    _commit(repo, {"script.py": script, "out.txt": "result\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": ["script.py"],
                "outs": ["out.txt"],
                "always_changed": True,
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5(script)}],
                "outs": [{"path": "out.txt", "md5": _md5("result\n")}],
            }
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "always-run"
    assert calc_overall_pipeline_status(statuses) == "up-to-date"


def test_always_run_stage_stays_always_run_despite_changes(tmp_path):
    """An always_run stage re-runs every time, so its staleness is moot: even a
    modified cmd and missing outputs read as ``always-run``, not stale (these
    stages often produce ephemeral outputs that aren't pushed to the hub)."""
    repo = _init_repo(tmp_path / "repo")
    script = "print('hi')\n"
    _commit(repo, {"script.py": script, "out.txt": "result\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py --new-flag",
                "deps": ["script.py"],
                "outs": ["data/out"],
                "always_changed": True,
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5(script)}],
                # output not in git, not in (empty) storage -> would be missing
                "outs": [{"path": "data/out", "md5": f"{_md5('c')}.dir"}],
            }
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "always-run"


def test_frozen_stage_with_real_change_is_not_stale(tmp_path):
    """A frozen stage is pinned, so even a modified cmd reads as frozen."""
    repo = _init_repo(tmp_path / "repo")
    script = "print('hi')\n"
    _commit(repo, {"script.py": script, "out.txt": "result\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml = {
        "stages": {
            "run": {
                "cmd": "python script.py --new-flag",
                "deps": ["script.py"],
                "outs": ["out.txt"],
                "frozen": True,
            }
        }
    }
    dvc_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": _md5(script)}],
                "outs": [{"path": "out.txt", "md5": _md5("result\n")}],
            }
        }
    }
    statuses = compute_stage_statuses(
        dvc_yaml, dvc_lock, tree, "o", "p", FakeFS()
    )
    assert statuses["run"].status == "frozen"


def test_find_stage_for_path_directory_output():
    """Issue 622: a figure produced into a stage's output *directory* must map
    back to that stage, not just on an exact out-path match."""
    dvc_lock = {
        "stages": {
            "plot": {"outs": [{"path": "figures", "md5": "abc123.dir"}]},
            "report": {"outs": [{"path": "results/sup.json", "md5": "x"}]},
        }
    }
    assert find_stage_for_path("figures/test.png", dvc_lock) == "plot"
    assert find_stage_for_path("figures/sub/deep.png", dvc_lock) == "plot"
    assert find_stage_for_path("results/sup.json", dvc_lock) == "report"
    assert find_stage_for_path("other/x.png", dvc_lock) is None
    # An exact out-path match wins over a containing-directory match.
    dvc_lock_both = {
        "stages": {
            "dir": {"outs": [{"path": "figures", "md5": "d.dir"}]},
            "file": {"outs": [{"path": "figures/test.png", "md5": "f"}]},
        }
    }
    assert find_stage_for_path("figures/test.png", dvc_lock_both) == "file"


def test_without_cache_token_always_recomputes(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    script = "print('hi')\n"
    _commit(repo, {"script.py": script, "out.txt": "result\n"}, "init")
    tree = get_repo_tree_for_ref(repo, None)
    dvc_yaml, dvc_lock = _simple_pipeline(script)
    up = compute_stage_statuses(dvc_yaml, dvc_lock, tree, "o", "p", FakeFS())
    assert up["run"].status == "up-to-date"
    stale_lock = {
        "stages": {
            "run": {
                "cmd": "python script.py",
                "deps": [{"path": "script.py", "md5": "deadbeef"}],
                "outs": [{"path": "out.txt", "md5": _md5("result\n")}],
            }
        }
    }
    stale = compute_stage_statuses(
        dvc_yaml, stale_lock, tree, "o", "p", FakeFS()
    )
    assert stale["run"].status == "stale"


def test_precompute_storage_presence_lists_then_falls_back() -> None:
    present = "a" * 32
    absent = "b" * 32
    dvc_lock = {
        "stages": {
            "train": {
                "deps": [{"path": "in.csv", "md5": present}],
                "outs": [{"path": "out.pkl", "md5": absent}],
            }
        }
    }
    # Normal path: one listing per layout, and no per-md5 probing at all.
    fs = FakeFS(existing_md5s={present})
    presence = _precompute_storage_presence(dvc_lock, "owner", "proj", fs)
    assert presence == {present: True, absent: False}
    assert fs.find_calls == 2
    assert fs.exists_calls == 0
    # When listing fails, fall back to probing each md5 and get the same
    # answer rather than reporting everything as missing.
    fallback_fs = FakeFS(
        existing_md5s={present}, find_error=OSError("listing unavailable")
    )
    fallback = _precompute_storage_presence(
        dvc_lock, "owner", "proj", fallback_fs
    )
    assert fallback == presence
    assert fallback_fs.exists_calls > 0
    # A project that has pushed nothing reports everything missing.
    empty = _precompute_storage_presence(dvc_lock, "owner", "proj", FakeFS())
    assert empty == {present: False, absent: False}


def test_find_stage_for_path_prefers_current_stages():
    # dvc.lock keeps entries that are no longer real stages: a bare name left
    # from before the stage became a matrix, and expansions from an older
    # matrix shape. Staleness reporting drops both, so matching one pins a
    # figure to a stage that can never have a status.
    dvc_lock = {
        "stages": {
            "plot": {"outs": [{"path": "figures/a.png"}]},
            "plot@_arg00-9": {"outs": [{"path": "figures/a.png"}]},
            "plot@_arg00": {"outs": [{"path": "figures/a.png"}]},
            "render": {"outs": [{"path": "figures/sub"}]},
            "render@_arg00": {"outs": [{"path": "figures/sub"}]},
            "orphan": {"outs": [{"path": "figures/gone.png"}]},
        }
    }
    current = {"plot@_arg00", "render@_arg00"}
    # An exact match on a current expansion wins over the stale bare entry and
    # the stale expansion, whatever order they appear in.
    assert (
        find_stage_for_path("figures/a.png", dvc_lock, valid_stages=current)
        == "plot@_arg00"
    )
    # Directory outs resolve the same way, including for nested paths.
    assert (
        find_stage_for_path(
            "figures/sub/deep.png", dvc_lock, valid_stages=current
        )
        == "render@_arg00"
    )
    # With nothing current producing it, naming the stale stage still beats
    # naming nothing.
    assert (
        find_stage_for_path("figures/gone.png", dvc_lock, valid_stages=current)
        == "orphan"
    )
    assert (
        find_stage_for_path("nope.png", dvc_lock, valid_stages=current) is None
    )
    # Omitting valid_stages keeps the old any-match behaviour.
    assert find_stage_for_path("figures/a.png", dvc_lock) == "plot"
