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
    ``!results/StageName/end.json`` has no effect. The fix converts the
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
    # Keep the rules minimal while preserving the required behavior
    assert lines == [
        "results/*",
        "!results/StageName/",
        "results/StageName/*",
        "!results/StageName/end.json",
    ]
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


def test_ensure_path_is_not_ignored_nested_direct_path_rule(tmp_dir):
    """Unignoring a directly ignored nested path should only remove that
    rule.
    """
    repo = git.Repo.init()
    target = "pubs/applied-ocean-research-model/references.bib"
    sibling = "pubs/applied-ocean-research-model/paper.pdf"
    with open(".gitignore", "w") as f:
        f.write(f"{target}\n")
    os.makedirs("pubs/applied-ocean-research-model", exist_ok=True)
    with open(target, "w") as f:
        f.write("@article{test}\n")
    with open(sibling, "w") as f:
        f.write("pdf\n")
    # Only the direct target path should be ignored initially
    assert repo.ignored(target)
    assert not repo.ignored(sibling)
    result = calkit.git.ensure_path_is_not_ignored(repo, path=target)
    assert result is True
    with open(".gitignore") as f:
        lines = f.read().splitlines()
    # Remove only the direct rule, with no recursive ancestor entries
    assert target not in lines
    assert f"!{target}" not in lines
    assert "!pubs/" not in lines
    assert "pubs/*" not in lines
    assert "!pubs/applied-ocean-research-model/" not in lines
    assert "pubs/applied-ocean-research-model/*" not in lines
    assert not repo.ignored(target)
    assert not repo.ignored(sibling)


def test_ensure_path_is_not_ignored_nested_gitignore_direct_path_rule(tmp_dir):
    repo = git.Repo.init()
    os.makedirs("paper", exist_ok=True)
    target = "paper/main.pdf"
    with open("paper/.gitignore", "w") as f:
        f.write("/main.pdf\n")
    with open(target, "w") as f:
        f.write("pdf\n")
    assert repo.ignored(target)
    result = calkit.git.ensure_path_is_not_ignored(repo, path=target)
    assert result is True
    with open("paper/.gitignore") as f:
        lines = f.read().splitlines()
    assert "/main.pdf" not in lines
    assert "!/main.pdf" not in lines
    assert not os.path.exists(".gitignore")
    assert not repo.ignored(target)


def test_ensure_path_is_not_ignored_both_root_and_subdir_gitignore(tmp_dir):
    """Un-ignoring a path blocked by BOTH the root gitignore AND a subdirectory
    gitignore should fix both files so the path truly becomes unignored.

    When the root .gitignore excludes a directory (e.g. ``pubs/``) and a
    nested .gitignore (e.g. created by DVC) also excludes the same file, the
    function must recursively remove every blocking rule.
    """
    repo = git.Repo.init()
    os.makedirs("pubs", exist_ok=True)
    target = "pubs/references.bib"
    sibling = "pubs/other.pdf"
    with open(target, "w") as f:
        f.write("@article{test}\n")
    with open(sibling, "w") as f:
        f.write("pdf\n")
    # Root gitignore excludes the whole pubs/ directory
    with open(".gitignore", "w") as f:
        f.write("pubs/\n")
    # Subdirectory .gitignore (e.g. managed by DVC) also excludes the file
    with open("pubs/.gitignore", "w") as f:
        f.write("references.bib\n")
    assert repo.ignored(target)
    result = calkit.git.ensure_path_is_not_ignored(repo, path=target)
    assert result is True
    # The file must no longer be ignored
    assert not repo.ignored(target)
    # Other files in pubs/ should still be ignored
    assert repo.ignored(sibling)
    # references.bib should be gone from the subdirectory gitignore
    with open("pubs/.gitignore") as f:
        sub_lines = f.read().splitlines()
    assert "references.bib" not in sub_lines


def test_ensure_path_is_not_ignored_glob_in_parent_subdir_gitignore(tmp_dir):
    """Un-ignoring a nested path matched by a glob in a parent subdirectory's
    .gitignore should add an appropriate negation.
    """
    repo = git.Repo.init()
    os.makedirs("pubs/output", exist_ok=True)
    target = "pubs/output/paper.pdf"
    sibling = "pubs/output/other.pdf"
    with open(target, "w") as f:
        f.write("pdf\n")
    with open(sibling, "w") as f:
        f.write("pdf\n")
    with open("pubs/.gitignore", "w") as f:
        f.write("*.pdf\n")
    assert repo.ignored(target)
    result = calkit.git.ensure_path_is_not_ignored(repo, path=target)
    assert result is True
    assert not repo.ignored(target)
    # Other pdfs under pubs/ should still be ignored
    assert repo.ignored(sibling)


def test_ensure_path_is_ignored_removes_stale_negation(tmp_dir):
    """Re-ignoring a path that was previously un-ignored with a negation should
    remove the stale negation entry so the .gitignore stays clean.
    """
    repo = git.Repo.init()
    os.makedirs("results", exist_ok=True)
    target = "results/output.json"
    other = "results/other.json"
    with open(target, "w") as f:
        f.write("{}")
    with open(other, "w") as f:
        f.write("{}")
    # State after a previous ensure_path_is_not_ignored on target
    with open(".gitignore", "w") as f:
        f.write("results/*\n!results/output.json\n")
    assert not repo.ignored(target)
    # Now re-ignore it (e.g. moving back to DVC tracking)
    result = calkit.git.ensure_path_is_ignored(repo, path=target)
    assert result is True
    assert repo.ignored(target)
    with open(".gitignore") as f:
        lines = f.read().splitlines()
    # Stale negation must be removed
    assert "!results/output.json" not in lines
    # Other files in results/ should still be ignored
    assert repo.ignored(other)


def test_ensure_path_is_ignored_nested_no_complex_patterns(tmp_dir):
    """Ignoring a nested path whose parent directory is NOT ignored should just
    add the direct path rule without any recursive ancestor patterns.
    """
    repo = git.Repo.init()
    os.makedirs("pubs/paper", exist_ok=True)
    target = "pubs/paper/main.pdf"
    sibling = "pubs/paper/other.pdf"
    with open(target, "w") as f:
        f.write("pdf\n")
    with open(sibling, "w") as f:
        f.write("pdf\n")
    result = calkit.git.ensure_path_is_ignored(repo, path=target)
    assert result is True
    with open(".gitignore") as f:
        lines = f.read().splitlines()
    # Should only contain the direct path, no complex recursive patterns
    assert target in lines
    assert "!pubs/" not in lines
    assert "pubs/*" not in lines
    assert "!pubs/paper/" not in lines
    assert "pubs/paper/*" not in lines
    assert repo.ignored(target)
    assert not repo.ignored(sibling)


def test_ensure_path_is_not_ignored_multiple_files_excluded_dir(tmp_dir):
    """Un-ignoring multiple files in the same excluded directory should produce
    clean, non-duplicated rules and keep other files ignored.
    """
    repo = git.Repo.init()
    os.makedirs("results", exist_ok=True)
    for name in ["a.json", "b.json", "c.json"]:
        with open(f"results/{name}", "w") as f:
            f.write("{}")
    with open(".gitignore", "w") as f:
        f.write("results/\n")
    # Un-ignore two files
    calkit.git.ensure_path_is_not_ignored(repo, path="results/a.json")
    calkit.git.ensure_path_is_not_ignored(repo, path="results/b.json")
    assert not repo.ignored("results/a.json")
    assert not repo.ignored("results/b.json")
    # Third file must remain ignored
    assert repo.ignored("results/c.json")
    with open(".gitignore") as f:
        lines = f.read().splitlines()
    # The glob rule for the directory should appear only once
    assert lines.count("results/*") == 1


def test_ensure_path_is_not_ignored_dvc_subdir_gitignore(tmp_dir):
    """When DVC manages a .gitignore in a subdirectory (e.g. outputs/.gitignore
    with '/model.fig'), un-ignoring model.fig should remove just that entry,
    leaving other DVC-tracked files (model.mat) still ignored.
    """
    repo = git.Repo.init()
    os.makedirs("outputs", exist_ok=True)
    with open("outputs/model.fig", "w") as f:
        f.write("fig")
    with open("outputs/model.mat", "w") as f:
        f.write("mat")
    # DVC creates anchored entries in the directory's .gitignore
    with open("outputs/.gitignore", "w") as f:
        f.write("/model.fig\n/model.mat\n")
    assert repo.ignored("outputs/model.fig")
    assert repo.ignored("outputs/model.mat")
    result = calkit.git.ensure_path_is_not_ignored(
        repo, path="outputs/model.fig"
    )
    assert result is True
    assert not repo.ignored("outputs/model.fig")
    # model.mat must still be ignored
    assert repo.ignored("outputs/model.mat")
    with open("outputs/.gitignore") as f:
        sub_lines = f.read().splitlines()
    assert "/model.fig" not in sub_lines
    assert "/model.mat" in sub_lines


def test_ensure_path_is_ignored_stale_negation_after_direct_rule(tmp_dir):
    """Re-ignoring a path where the .gitignore has both the direct rule AND a
    stale negation *after* it (so the negation wins and the path is currently
    unignored) must remove the negation so the direct rule takes effect.
    """
    repo = git.Repo.init()
    os.makedirs("results", exist_ok=True)
    target = "results/output.json"
    with open(target, "w") as f:
        f.write("{}")
    # The direct rule comes first, but the negation after it wins, so the
    # path is currently NOT ignored.
    with open(".gitignore", "w") as f:
        f.write("results/output.json\n!results/output.json\n")
    assert not repo.ignored(target)
    result = calkit.git.ensure_path_is_ignored(repo, path=target)
    assert result is True
    assert repo.ignored(target)
    with open(".gitignore") as f:
        lines = f.read().splitlines()
    assert "!results/output.json" not in lines
    assert "results/output.json" in lines
