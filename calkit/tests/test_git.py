"""Tests for ``calkit.git``."""

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
