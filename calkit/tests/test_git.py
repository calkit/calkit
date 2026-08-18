"""Tests for ``calkit.git``."""

import os
import subprocess
import sys
from pathlib import Path

import git
import pytest

import calkit

# These tests pass on POSIX but fail on Windows where GitPython's repo.ignored
# returns [] after calkit.git.ensure_path_is_not_ignored modifies a multi-level
# set of .gitignore files. Needs debugging on a real Windows checkout.
skipif_windows_gitignore = pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: ensure_path_is_(not_)ignored multi-level gitignore on Windows",
)


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


@skipif_windows_gitignore
def test_ensure_path_is_not_ignored_both_root_and_subdir_gitignore(tmp_dir):
    """Un-ignoring a path blocked by BOTH the root gitignore AND a subdirectory
    gitignore should fix both files so the path truly becomes unignored.

    When the root .gitignore excludes a directory (e.g., ``pubs/``) and a
    nested .gitignore (e.g., created by DVC) also excludes the same file, the
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
    # Subdirectory .gitignore (e.g., managed by DVC) also excludes the file
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


@skipif_windows_gitignore
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


@skipif_windows_gitignore
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
    # Now re-ignore it (e.g., moving back to DVC tracking)
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


@skipif_windows_gitignore
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
    """When DVC manages a .gitignore in a subdirectory (e.g., outputs/.gitignore
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


def test_resolve_ref_fetches_what_a_shallow_clone_lacks(tmp_dir):
    # A CI checkout is usually shallow and often has only the branch being
    # built, so a comparison against another branch fails on a repo that
    # looks fine otherwise
    import calkit.git

    origin = os.path.join(tmp_dir, "origin")
    os.makedirs(origin)
    subprocess.check_call(["git", "init", "-q", "-b", "main", origin])
    with open(os.path.join(origin, "f.txt"), "w") as f:
        f.write("one\n")
    subprocess.check_call(["git", "-C", origin, "add", "-A"])
    subprocess.check_call(
        [
            "git",
            "-C",
            origin,
            "-c",
            "user.email=t@e.com",
            "-c",
            "user.name=T",
            "commit",
            "-qm",
            "first",
        ]
    )
    main_sha = subprocess.check_output(
        ["git", "-C", origin, "rev-parse", "HEAD"], text=True
    ).strip()
    subprocess.check_call(["git", "-C", origin, "checkout", "-qb", "work"])
    with open(os.path.join(origin, "f.txt"), "w") as f:
        f.write("two\n")
    subprocess.check_call(
        [
            "git",
            "-C",
            origin,
            "-c",
            "user.email=t@e.com",
            "-c",
            "user.name=T",
            "commit",
            "-qam",
            "second",
        ]
    )
    clone = os.path.join(tmp_dir, "clone")
    subprocess.check_call(
        ["git", "clone", "-q", "--depth", "1", f"file://{origin}", clone]
    )
    repo = calkit.git.get_repo(clone)
    # The other branch isn't here at all, not even as a tracking ref
    assert repo.git.rev_parse("--is-shallow-repository").strip() == "true"
    assert calkit.git.resolve_ref(repo, "main") == main_sha
    # What's already here needs no network
    assert calkit.git.resolve_ref(repo, "HEAD") is not None
    # A revision that doesn't exist is reported as missing rather than
    # retried forever
    assert calkit.git.resolve_ref(repo, "nope-not-a-branch") is None


def test_check_branch_is_current(tmp_dir):
    # What matters isn't which branch the work happens on, but whether it
    # contains everything already on the trunk, since a branch missing that
    # can take shared state backwards.
    main_dir = os.path.join(str(tmp_dir), "main")
    remote_dir = os.path.join(str(tmp_dir), "remote")
    os.makedirs(main_dir)
    git.Repo.init(path=remote_dir, bare=True)
    repo = git.Repo.init(main_dir)
    with open(os.path.join(main_dir, "a.txt"), "w") as f:
        f.write("a")
    repo.git.add("a.txt")
    repo.git.commit(["-m", "First commit"])
    # With no remote and no other branch, there's nothing to check against
    assert calkit.git.check_branch_is_current(repo) is None
    default_branch = repo.active_branch.name
    repo.git.remote(["add", "origin", remote_dir])
    repo.git.push(["--set-upstream", "origin", default_branch])
    assert calkit.git.get_default_branch(repo) == default_branch
    # Being on the default branch passes, and so does a branch cut from its
    # tip, even before that branch has any commits of its own
    assert calkit.git.check_branch_is_current(repo) is None
    behind_from = repo.head.commit.hexsha
    repo.git.checkout(["-b", "fresh"])
    assert calkit.git.check_branch_is_current(repo) is None
    with open(os.path.join(main_dir, "b.txt"), "w") as f:
        f.write("b")
    repo.git.add("b.txt")
    repo.git.commit(["-m", "Work on a branch"])
    assert calkit.git.check_branch_is_current(repo) is None
    # A branch cut before something that landed on the default branch is not
    repo.git.checkout(default_branch)
    with open(os.path.join(main_dir, "c.txt"), "w") as f:
        f.write("c")
    repo.git.add("c.txt")
    repo.git.commit(["-m", "Work on the default branch"])
    repo.git.push()
    repo.git.checkout(["-b", "behind", behind_from])
    msg = calkit.git.check_branch_is_current(repo)
    assert msg is not None
    assert "behind" in msg
    assert "1 commit(s)" in msg
    # Merging what it's missing resolves it
    repo.git.merge(default_branch)
    assert calkit.git.check_branch_is_current(repo) is None
    # The default branch is held to the same standard, since a local copy of
    # it can be behind the remote everyone else pushes to
    repo.git.checkout(default_branch)
    repo.git.reset(["--hard", behind_from])
    msg = calkit.git.check_branch_is_current(repo)
    assert msg is not None
    assert f"'origin/{default_branch}'" in msg


def _install_stripping_filter(repo: git.Repo, pattern: str = "*.ipynb"):
    """Configure a clean filter that mangles content, the way nbstripout does.

    A stand-in for nbstripout so the test doesn't need it installed: what
    matters is that Git rewrites content on its way into the object store,
    not what the rewrite is.
    """
    # Spelled with no quotes, spaces, or backslashes in any token: Git runs
    # filter commands through a shell---its bundled sh on Windows---which eats
    # the backslashes in a Windows interpreter path, leaving a command that
    # never runs. Marked required so that failure is a loud error instead of a
    # silent pass-through that looks like the content was never filtered.
    repo.git.config("filter.stripper.clean", "sed -e s/.*/stripped/")
    repo.git.config("filter.stripper.required", "true")
    attributes = Path(repo.git_dir) / "info" / "attributes"
    attributes.parent.mkdir(parents=True, exist_ok=True)
    attributes.write_text(f"{pattern} filter=stripper\n")


def test_get_filter_driver(tmp_dir):
    repo = git.Repo.init()
    Path("nb.ipynb").write_text("real content")
    assert calkit.git.get_filter_driver(repo, "nb.ipynb") is None
    _install_stripping_filter(repo)
    assert calkit.git.get_filter_driver(repo, "nb.ipynb") == "stripper"
    # A path the pattern doesn't cover is untouched.
    assert calkit.git.get_filter_driver(repo, "notes.txt") is None


def test_ensure_path_is_not_filtered(tmp_dir):
    repo = git.Repo.init()
    repo.git.config("user.email", "test@example.com")
    repo.git.config("user.name", "Test")
    _install_stripping_filter(repo)
    path = ".calkit/notebooks/executed/nb.ipynb"
    Path(path).parent.mkdir(parents=True)
    Path(path).write_text("real content")
    Path("other.ipynb").write_text("real content")
    repo.git.add("-A")
    repo.git.commit("-m", "Init")
    # The committed bytes don't match the working tree, and nothing shows as
    # modified, which is what makes this worth guarding against.
    assert repo.git.show(f"HEAD:{path}") == "stripped", (
        "the stand-in clean filter didn't run, so there's nothing here for "
        "the exemption to fix; check that its command works on this platform"
    )
    assert not repo.git.status("--porcelain")
    assert calkit.git.ensure_path_is_not_filtered(repo, path=path)
    assert calkit.git.get_filter_driver(repo, path) is None
    # The exemption is scoped: everything else stays filtered.
    assert calkit.git.get_filter_driver(repo, "other.ipynb") == "stripper"
    # Already-committed content is repaired rather than left for the next run.
    repo.git.commit("-m", "Unfilter")
    assert repo.git.show(f"HEAD:{path}") == "real content"
    assert repo.git.show("HEAD:other.ipynb") == "stripped"
    # Idempotent: a second call neither re-adds the rule nor errors.
    attributes = Path(repo.git_dir) / "info" / "attributes"
    before = attributes.read_text()
    assert calkit.git.ensure_path_is_not_filtered(repo, path=path) is None
    assert attributes.read_text() == before


def test_ensure_path_is_not_filtered_no_filter(tmp_dir):
    """A repo with no filters is left completely alone."""
    repo = git.Repo.init()
    Path("nb.ipynb").write_text("real content")
    assert (
        calkit.git.ensure_path_is_not_filtered(repo, path="nb.ipynb") is None
    )
    assert not os.path.exists(Path(repo.git_dir) / "info" / "attributes")
