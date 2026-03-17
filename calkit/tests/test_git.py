"""Tests for ``calkit.git``."""

import os
from pathlib import Path

import git

import calkit


def test_ensure_path_is_ignored(tmp_dir):
    repo = git.Repo.init()
    with open("test.txt", "w") as f:
        f.write("test")
    calkit.git.ensure_path_is_ignored(repo, path="test.txt")
    with open(".gitignore") as f:
        gi = f.read()
    assert "test.txt" in gi.splitlines()
    repo.git.add("test.txt", "--force")
    calkit.git.ensure_path_is_ignored(repo, path="test.txt")
    with open(".gitignore") as f:
        gi2 = f.read()
    assert gi == gi2
    # Test a path in a submodule is ignored from the parent repo context.
    sub_path = Path("sub")
    sub_path.mkdir()
    submodule_repo = git.Repo.init(sub_path)

    class FakeSubmodule:
        path = "sub"

        def module(self):
            return submodule_repo

    class RepoWithSubmodule:
        def __init__(self, wrapped_repo):
            self.working_dir = wrapped_repo.working_dir
            self.submodules = [FakeSubmodule()]
            self._wrapped_repo = wrapped_repo

        def ignored(self, path):
            return self._wrapped_repo.ignored(path)

    repo_with_submodule = RepoWithSubmodule(repo)
    with open("sub/test.txt", "w") as f:
        f.write("test")
    calkit.git.ensure_path_is_ignored(repo_with_submodule, path="sub/test.txt")  # type: ignore
    with open("sub/.gitignore") as f:
        gi_sub = f.read()
    assert "test.txt" in gi_sub.splitlines()
    with open(".gitignore") as f:
        gi_root = f.read()
    assert "sub/test.txt" not in gi_root.splitlines()


def test_ensure_path_is_not_ignored(tmp_dir):
    repo = git.Repo.init()
    with open("test.txt", "w") as f:
        f.write("test")
    calkit.git.ensure_path_is_ignored(repo, path="test.txt")
    with open(".gitignore") as f:
        gi = f.read()
    assert "test.txt" in gi.splitlines()
    calkit.git.ensure_path_is_not_ignored(repo, path="test.txt")
    with open(".gitignore") as f:
        gi2 = f.read()
    assert "test.txt" not in gi2.splitlines()
    # Test a path in a submodule is unignored from the parent repo context.
    sub_path = Path("sub")
    sub_path.mkdir()
    submodule_repo = git.Repo.init(sub_path)
    with open("sub/.gitignore", "w") as f:
        f.write("test.txt\n")
    with open("sub/test.txt", "w") as f:
        f.write("test")

    class FakeSubmodule:
        path = "sub"

        def module(self):
            return submodule_repo

    class RepoWithSubmodule:
        def __init__(self, wrapped_repo):
            self.working_dir = wrapped_repo.working_dir
            self.submodules = [FakeSubmodule()]
            self._wrapped_repo = wrapped_repo

        def ignored(self, path):
            return self._wrapped_repo.ignored(path)

    repo_with_submodule = RepoWithSubmodule(repo)
    calkit.git.ensure_path_is_not_ignored(
        repo_with_submodule,  # type: ignore
        path="sub/test.txt",
    )
    with open("sub/.gitignore") as f:
        gi_sub = f.read().splitlines()
    assert "test.txt" not in gi_sub
    assert "!test.txt" not in gi_sub


def test_ensure_path_is_not_ignored_nested(tmp_dir):
    """Test that nested paths in ignored directories are correctly un-ignored.

    When a parent directory is excluded with a trailing slash (e.g.,
    ``results/``), git will not traverse into it, so a simple negation like
    ``!results/StageName/end.json`` has no effect.  The fix converts the
    directory exclude to a glob pattern and adds intermediate un-ignore rules.
    """
    repo = git.Repo.init()
    # Ignore the entire results/ directory
    with open(".gitignore", "w") as f:
        f.write("results/\n")
    # Create the nested target file so git can evaluate ignore status
    os.makedirs("results/StageName", exist_ok=True)
    with open("results/StageName/end.json", "w") as f:
        f.write("{}")
    # The file must be ignored before we try to un-ignore it
    assert repo.ignored("results/StageName/end.json")
    result = calkit.git.ensure_path_is_not_ignored(
        repo, path="results/StageName/end.json"
    )
    assert result is True
    with open(".gitignore") as f:
        lines = f.read().splitlines()
    # The plain directory exclude should be replaced with a glob
    assert "results/" not in lines
    assert "results/*" in lines
    # Intermediate directory must be un-ignored so git traverses into it
    assert "!results/StageName/" in lines
    # The intermediate directory's other contents must be re-ignored
    assert "results/StageName/*" in lines
    # The specific file must be explicitly un-ignored
    assert "!results/StageName/end.json" in lines
    # Verify git no longer considers the target file as ignored
    assert not repo.ignored("results/StageName/end.json")
    # Other files in results/ must still be ignored
    with open("results/other.txt", "w") as f:
        f.write("other")
    assert repo.ignored("results/other.txt")
    # Other files in the intermediate directory must still be ignored
    with open("results/StageName/other.json", "w") as f:
        f.write("{}")
    assert repo.ignored("results/StageName/other.json")
    # Calling again should be a no-op (path is no longer ignored)
    result2 = calkit.git.ensure_path_is_not_ignored(
        repo, path="results/StageName/end.json"
    )
    assert result2 is None
