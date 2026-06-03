"""Tests for ``cli.new``."""

import os
import re
import subprocess
import sys

import git
import pytest

import calkit
from calkit.environments import get_env_lock_fpath


def test_new_foreach_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "foreach-stage",
            "-n",
            "stage1",
            "--cmd",
            "echo {var} > {var}.txt",
            "--out",
            "{var}.txt",
            "one",
            "two",
            "three",
        ]
    )
    subprocess.check_call(["calkit", "run"])
    assert os.path.isfile("one.txt")
    # Add another stage that depends on one of these outputs
    subprocess.check_call(
        [
            "calkit",
            "new",
            "foreach-stage",
            "-n",
            "stage2",
            "--cmd",
            "cat {var}.txt > {var}-2.txt",
            "--out",
            "{var}-2.txt",
            "--dep",
            "{var}.txt",
            "one",
            "two",
            "three",
        ]
    )
    subprocess.check_call(["calkit", "run"])
    assert os.path.isfile("two-2.txt")


def test_new_figure(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "figure",
            "--title",
            "This is a cool figure",
            "--description",
            "This is a cool description",
            "myfigure.png",
        ]
    )
    ck_info = calkit.load_calkit_info()
    assert "myfigure.png" in [fig["path"] for fig in ck_info["figures"]]
    # Check that we won't overwrite a figure
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            [
                "calkit",
                "new",
                "figure",
                "--title",
                "This is a cool figure",
                "--description",
                "This is a cool description",
                "myfigure.png",
            ]
        )
    # Check that we can create a stage
    subprocess.check_call(
        [
            "calkit",
            "new",
            "figure",
            "--title",
            "This is a cool figure 2",
            "--description",
            "This is the description.",
            "myfigure2.png",
            "--stage",
            "create-figure",
            "--cmd",
            "python plot.py",
            "--dep",
            "plot.py",
            "--dep",
            "data.csv",
        ]
    )
    pipeline = calkit.dvc.read_pipeline()
    stage = pipeline["stages"]["create-figure"]
    assert stage["cmd"] == "python plot.py"
    assert set(stage["deps"]) == set(["plot.py", "data.csv"])
    assert stage["outs"] == ["myfigure2.png"]
    # Test that we can use outs from stage
    subprocess.check_call(
        [
            "calkit",
            "new",
            "figure",
            "myfigure3.png",
            "--title",
            "This is a cool figure 3",
            "--description",
            "This is the description.",
            "--stage",
            "create-figure3",
            "--cmd",
            "python plot.py",
            "--deps-from-stage-outs",
            "create-figure",
        ]
    )
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["create-figure3"]["deps"] == ["myfigure2.png"]


def test_new_publication(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "publication",
            "my-paper",
            "--template",
            "latex/article",
            "--kind",
            "journal-article",
            "--title",
            "This is a cool title",
            "--description",
            "This is a cool description.",
            "--stage",
            "build-latex-article",
            "--environment",
            "my-latex-env",
        ]
    )
    ck_info = calkit.load_calkit_info()
    print(ck_info)
    assert ck_info["environments"]["my-latex-env"] == dict(
        kind="docker",
        image="texlive/texlive:latest-full",
        description="TeXlive full.",
    )
    assert ck_info["publications"][0]["path"] == "my-paper/paper.pdf"
    stage = ck_info["pipeline"]["stages"]["build-latex-article"]
    assert stage["kind"] == "latex"
    assert stage["environment"] == "my-latex-env"
    assert stage["target_path"] == "my-paper/paper.tex"
    assert stage["outputs"] == ["my-paper/paper.pdf"]


def test_new_uv_env(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-env",
            "--name",
            "my-uv-env",
            "--python",
            "3.13",
            "requests",
        ]
    )
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["my-uv-env"]
    assert env["path"] == "pyproject.toml"
    # Test one in a subdirectory when another env already exists
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-env",
            "--name",
            "main",
            "--path",
            ".calkit/envs/main/pyproject.toml",
            "--python",
            "3.13",
            "requests",
        ]
    )
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["main"]
    assert env["path"] == ".calkit/envs/main/pyproject.toml"


def test_new_uv_venv(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "my-uv-venv",
            "pandas>=2.0",
            "matplotlib",
        ]
    )
    ck_info = calkit.load_calkit_info_object()
    envs = ck_info.environments
    env = envs["my-uv-venv"]
    assert isinstance(env, calkit.models.UvVenvEnvironment)
    assert env.path == "requirements.txt"
    assert env.prefix == ".venv"
    assert env.kind == "uv-venv"
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "my-uv-venv2",
            "--path",
            "requirements-2.txt",
            "--prefix",
            ".venv2",
            "pandas>=2.0",
            "matplotlib",
        ]
    )
    ck_info = calkit.load_calkit_info_object()
    envs = ck_info.environments
    env = envs["my-uv-venv2"]
    assert isinstance(env, calkit.models.UvVenvEnvironment)
    assert env.path == "requirements-2.txt"
    assert env.prefix == ".venv2"
    assert env.kind == "uv-venv"


def test_new_conda_env(tmp_dir):
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump(
            {
                "dependencies": ["python", "requests"],
                "name": "whatever",
                "channels": ["conda-forge"],
            },
            f,
        )
    subprocess.check_call(
        ["calkit", "new", "project", ".", "--name", "test", "--title", "Test"]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--path",
            "environment.yml",
            "--name",
            "e1",
            "--no-check",
        ]
    )
    with open("environment.yml") as f:
        env = calkit.ryaml.load(f)
    assert env["name"] == "test.e1"
    assert env["dependencies"] == ["python", "requests"]


def test_new_project(tmp_dir):
    subprocess.check_call(
        ["calkit", "new", "project", ".", "--title", "My new project"]
    )
    repo = git.Repo()
    assert repo.git.ls_files("calkit.yaml")
    assert repo.git.ls_files("README.md")
    assert repo.git.ls_files(".devcontainer")
    ck_info = calkit.load_calkit_info()
    assert ck_info["title"] == "My new project"


def test_new_project_existing_repo(tmp_dir):
    subprocess.check_call(["git", "init"])
    subprocess.check_call(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/someone/somerepo.git",
        ]
    )
    subprocess.check_call(
        ["calkit", "new", "project", ".", "--title", "My new project"]
    )
    repo = git.Repo()
    assert repo.git.ls_files("calkit.yaml")
    assert repo.git.ls_files("README.md")
    assert repo.git.ls_files(".devcontainer")
    ck_info = calkit.load_calkit_info()
    assert ck_info["title"] == "My new project"


def test_new_project_existing_files(tmp_dir):
    subprocess.check_call(["touch", "some-existing-file.txt"])
    subprocess.check_call(
        ["calkit", "new", "project", ".", "--title", "My new project"]
    )
    repo = git.Repo()
    assert "some-existing-file.txt" in repo.untracked_files
    assert repo.git.ls_files("calkit.yaml")
    assert repo.git.ls_files("README.md")
    assert not repo.git.ls_files("some-other-file.txt")
    assert repo.git.ls_files(".devcontainer")
    ck_info = calkit.load_calkit_info()
    assert ck_info["title"] == "My new project"


def test_new_project_cloud(tmp_dir, monkeypatch, httpserver):
    monkeypatch.setenv(
        "CALKIT_CLOUD_BASE_URL", httpserver.url_for("").rstrip("/")
    )
    monkeypatch.setenv("CALKIT_TEST_TOKEN", "test-token")
    project_resp = {
        "id": "00000000-0000-0000-0000-000000000001",
        "owner_account_id": "00000000-0000-0000-0000-000000000002",
        "owner_account_name": "test-user",
        "owner_account_display_name": "Test User",
        "owner_account_type": "user",
        "name": "my-project",
        "title": "My Project",
        "description": None,
        "is_public": False,
        "git_repo_url": "https://github.com/test-user/my-project",
        "created": "2024-01-01T00:00:00",
        "updated": "2024-01-01T00:00:00",
        "latest_git_rev": None,
        "status": None,
        "status_updated": None,
        "status_message": None,
        "current_user_access": "owner",
    }
    # Test `new project .` in an existing git repo with a remote
    httpserver.expect_ordered_request(
        "/projects", method="POST"
    ).respond_with_json(project_resp)
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["git", "config", "user.name", "Test User"])
    subprocess.check_call(["git", "config", "user.email", "test@example.com"])
    subprocess.check_call(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/test-user/my-project.git",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "project",
            ".",
            "--title",
            "My Project",
            "--cloud",
        ]
    )
    ck_info = calkit.load_calkit_info()
    assert ck_info["title"] == "My Project"
    assert ck_info["owner"] == "test-user"
    assert ck_info["name"] == "my-project"
    assert ck_info["git_repo_url"] == "https://github.com/test-user/my-project"
    repo = git.Repo()
    assert repo.remotes.origin.url == "https://github.com/test-user/my-project"
    assert not repo.is_dirty(untracked_files=True)
    # Test 403: remote owner is an org not in Calkit Cloud; error should
    # surface the detected org name and a helpful hint
    httpserver.expect_ordered_request(
        "/projects", method="POST"
    ).respond_with_json(
        {
            "detail": (
                "Can only create projects for yourself or organizations "
                "you belong to"
            )
        },
        status=403,
    )
    result = subprocess.run(
        [
            "calkit",
            "new",
            "project",
            ".",
            "--title",
            "My Project",
            "--cloud",
            "--overwrite",
            "--git-url",
            "https://github.com/some-org/some-project",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "some-org" in result.stderr
    assert "organization exists in Calkit Cloud" in result.stderr
    # Test that a non-'origin' remote name is handled correctly
    httpserver.expect_ordered_request(
        "/projects", method="POST"
    ).respond_with_json(project_resp)
    subprocess.check_call(["git", "remote", "rename", "origin", "upstream"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "project",
            ".",
            "--title",
            "My Project",
            "--cloud",
            "--overwrite",
        ]
    )
    repo = git.Repo()
    assert (
        repo.remotes.upstream.url == "https://github.com/test-user/my-project"
    )


def test_new_python_script_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open("script.py", "w") as f:
        f.write("print('Hello, world!')")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "--name",
            "py",
            "--python",
            "3.13",
            "requests",
            "--no-check",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "python-script-stage",
            "--name",
            "run-script",
            "--script-path",
            "script.py",
            "--environment",
            "py",
            "--output",
            "output.txt",
        ]
    )
    subprocess.check_call(["calkit", "check", "pipeline", "--compile"])
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["run-script"]["cmd"] == (
        "calkit xenv -n py --no-check -- python script.py"
    )
    env_lock_fpath = get_env_lock_fpath(
        calkit.load_calkit_info()["environments"]["py"], "py", for_dvc=True
    )
    assert set(pipeline["stages"]["run-script"]["deps"]) == set(
        ["script.py", env_lock_fpath]
    )
    assert pipeline["stages"]["run-script"]["outs"] == ["output.txt"]
    subprocess.check_call(
        [
            "calkit",
            "new",
            "python-script-stage",
            "--name",
            "run-script-2",
            "--script-path",
            "script2.py",
            "--arg",
            "{name}",
            "--environment",
            "py",
            "--output",
            "output-{name}.txt",
            "--iter",
            "name",
            "bob,joe,sally",
        ]
    )
    subprocess.check_call(["calkit", "check", "pipeline", "--compile"])
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["run-script-2"]["cmd"] == (
        "calkit xenv -n py --no-check -- python script2.py ${item.name}"
    )
    assert pipeline["stages"]["run-script-2"]["outs"] == [
        "output-${item.name}.txt"
    ]
    assert pipeline["stages"]["run-script-2"]["matrix"]["name"] == [
        "bob",
        "joe",
        "sally",
    ]


def test_new_latex_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open("paper.tex", "w") as f:
        f.write("Hello, world!")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "docker-env",
            "--name",
            "tex",
            "--image",
            "texlive/texlive:latest-full",
            "--no-check",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "latex-stage",
            "--name",
            "build-paper",
            "--target",
            "paper.tex",
            "--environment",
            "tex",
            "--output",
            "paper.pdf",
        ]
    )
    subprocess.check_call(["calkit", "check", "pipeline", "--compile"])
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["build-paper"]["cmd"] == (
        "calkit latex build -e tex --no-check paper.tex"
    )
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["tex"]
    env_lock_fpath = get_env_lock_fpath(env, "tex", for_dvc=True)
    assert set(pipeline["stages"]["build-paper"]["deps"]) == set(
        ["paper.tex", env_lock_fpath]
    )
    assert pipeline["stages"]["build-paper"]["outs"] == ["paper.pdf"]


def test_new_matlab_script_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("scripts")
    with open("scripts/script.m", "w") as f:
        f.write("disp('Hello, world!')")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "docker-env",
            "--name",
            "matlab1",
            "--image",
            "mathworks/matlab:latest",
            "--no-check",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "matlab-script-stage",
            "--name",
            "run-script1",
            "-e",
            "matlab1",
            "--script-path",
            "scripts/script.m",
            "--output",
            "results/output.txt",
            "--output",
            "results/output2.txt",
        ]
    )
    subprocess.check_call(["calkit", "check", "pipeline", "--compile"])
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["run-script1"]["cmd"] == (
        "calkit xenv -n matlab1 --no-check -- \"run('scripts/script.m');\""
    )
    env_lock_fpath = get_env_lock_fpath(
        calkit.load_calkit_info()["environments"]["matlab1"],
        "matlab1",
        for_dvc=True,
    )
    assert set(pipeline["stages"]["run-script1"]["deps"]) == set(
        ["scripts/script.m", env_lock_fpath]
    )
    assert pipeline["stages"]["run-script1"]["outs"] == [
        "results/output.txt",
        "results/output2.txt",
    ]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Julia env init fails on Windows GHA runners (Pkg stdlib missing)",
)
def test_new_julia_env(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "julia-env", "--name", "j1", "WaterLily"]
    )
    assert os.path.isfile("Project.toml")
    assert os.path.isfile("Manifest.toml")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "julia-env",
            "--name",
            "j2",
            "--julia",
            "1.10",
            "Revise",
            "--path",
            "envs/my-env/Project.toml",
        ]
    )
    assert os.path.isfile("envs/my-env/Project.toml")
    assert os.path.isfile("envs/my-env/Manifest.toml")
    # Test we can create an empty env with just a Project.toml
    subprocess.check_call(
        [
            "calkit",
            "new",
            "julia-env",
            "--name",
            "j3",
            "--julia",
            "1.10",
            "--path",
            "envs/empty/Project.toml",
        ]
    )
    assert os.path.isfile("envs/empty/Project.toml")
    assert not os.path.isfile("envs/empty/Manifest.toml")


def test_new_nix_env_stages_flake(tmp_dir):
    # ``nix flake lock`` refuses to see untracked files inside a Git
    # repo. ``calkit new nix-env`` must stage the freshly written
    # flake.nix before invoking the lock step, even when ``--no-check``
    # skips the lock itself -- we verify staging happens by checking
    # that the auto-commit captured flake.nix.
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "nix-env", "--name", "main", "python3", "--no-check"]
    )
    assert os.path.isfile("flake.nix")
    repo = git.Repo(".")
    head_files = [item.path for item in repo.head.commit.tree.traverse()]
    assert "flake.nix" in head_files
    assert "calkit.yaml" in head_files


def test_new_release(tmp_dir, monkeypatch, httpserver):
    # Set up a mock Zenodo API so the test doesn't depend on the real sandbox
    record_id = "test-record-abc123"
    doi = "10.5072/zenodo.test123"
    # Point the Zenodo base URL at the local mock server and provide a dummy
    # token so no real credentials are needed.  Both env vars are inherited
    # by every subprocess started by this test.
    monkeypatch.setenv(
        "CALKIT_INVENIO_BASE_URL_ZENODO",
        httpserver.url_for("").rstrip("/"),
    )
    monkeypatch.setenv("ZENODO_TOKEN", "test-token")
    # POST /records – create a new draft record
    httpserver.expect_request(
        re.compile(r"^/records$"), method="POST"
    ).respond_with_json({"id": record_id, "pids": {}})
    # POST /records/{id}/draft/files – initiate a file upload slot
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/files$"), method="POST"
    ).respond_with_json({"entries": []})
    # PUT /records/{id}/draft/files/{filename}/content – stream file bytes
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/files/.+/content$"),
        method="PUT",
    ).respond_with_data("", status=200)
    # POST /records/{id}/draft/files/{filename}/commit – finalise upload
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/files/.+/commit$"),
        method="POST",
    ).respond_with_json({"key": "file", "status": "completed"})
    # POST /records/{id}/draft/pids/doi – reserve a DOI for a draft
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/pids/doi$"), method="POST"
    ).respond_with_json({"pids": {"doi": {"identifier": doi}}})
    # GET /records/{id}/draft/files – list files already in the draft
    # (used by --reupload to decide which files to delete first)
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/files$"), method="GET"
    ).respond_with_json({"entries": []})
    # POST /records/{id}/draft/actions/publish – publish the draft
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/actions/publish$"),
        method="POST",
    ).respond_with_json(
        {"id": record_id, "pids": {"doi": {"identifier": doi}}}
    )
    # GET /records/{id} – fetch the published record for post-test assertions
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}$"), method="GET"
    ).respond_with_json(
        {
            "metadata": {
                "license": {"id": "cc-by-4.0"},
                "related_identifiers": [
                    {"identifier": ("https://github.com/calkit/test-project")}
                ],
            }
        }
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "project",
            ".",
            "--title",
            "Test project",
            "--name",
            "test-project",
        ]
    )
    subprocess.check_call(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/calkit/test-project.git",
        ]
    )
    # TODO: Add project description?
    # Add authors to CITATION.cff (the single source of truth for authors)
    authors = [
        {
            "first_name": "Alice",
            "last_name": "Smith",
            "affiliation": "SomeU",
            "orcid": "0000-0001-2345-6789",
        },
        {
            "first_name": "Bob",
            "last_name": "Jones",
            "affiliation": None,
            "orcid": None,
        },
    ]
    calkit.releases.set_cff_authors(authors)
    # Add a default license
    subprocess.check_call(
        [
            "calkit",
            "update",
            "license",
            "--copyright-holder",
            "Some Person",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "release",
            "--name",
            "v0.1.0",
            "--description",
            "First release.",
            "--draft",
            "--no-github",
            "--verbose",
        ]
    )
    ck_info = calkit.load_calkit_info()
    assert "v0.1.0" in ck_info["releases"]
    release = ck_info["releases"]["v0.1.0"]
    assert release["doi"] is not None
    # TODO: Test that the GitHub link is in the related works
    # Test that we can update this release
    # Side note: This is revealing some design weirdness where we're grouping
    # functionality under verbs and not the type of resource they act on
    # This leads to a more English-like CLI, but we may want to organize the
    # logic by resource type
    subprocess.check_call(
        ["calkit", "update", "release", "--name", "v0.1.0", "--reupload"]
    )
    # TODO: Check that the files were actually updated, not just that there
    # were not errors
    # TODO: Check that the git rev of the release was updated
    # Test publishing the release
    subprocess.check_call(
        [
            "calkit",
            "update",
            "release",
            "--latest",
            "--publish",
            "--no-github",
            "--no-push-tags",
        ]
    )
    # Check Git tags for the release name
    git_tags = git.Repo().tags
    assert "v0.1.0" in [tag.name for tag in git_tags]
    # Check the license is correct
    # TODO: It seems like we can't use multiple license IDs with the API
    record_id = release["record_id"]
    record = calkit.invenio.get(f"/records/{record_id}")
    metadata = record["metadata"]
    print(metadata)
    assert metadata["license"] == {"id": "cc-by-4.0"}
    related = metadata["related_identifiers"]
    assert related[0]["identifier"] == "https://github.com/calkit/test-project"
    # TODO: Test that we can delete the release
    # This will fail if it's not a draft
    # subprocess.check_call(
    #     ["calkit", "update", "release", "--name", "v0.1.0", "--delete"]
    # )


def test_new_release_publish_empty_pids(tmp_dir, monkeypatch, httpserver):
    """Regression test for issue #927.

    Zenodo's publish action returns 202 and its body may come back with an
    empty ``pids`` payload, so the DOI cannot be read from the publish
    response. We must not assume ``pids.doi.identifier`` is present: instead we
    reserve the DOI on the draft beforehand and recover the minted DOI by
    polling ``GET /records/{id}``. This mocks exactly that shape so a
    regression back to ``resp["pids"]["doi"]["identifier"]`` would fail here.
    """
    record_id = "test-record-empty-pids"
    reserved_doi = "10.5072/zenodo.reserved999"
    monkeypatch.setenv(
        "CALKIT_INVENIO_BASE_URL_ZENODO",
        httpserver.url_for("").rstrip("/"),
    )
    monkeypatch.setenv("ZENODO_TOKEN", "test-token")
    # Create draft
    httpserver.expect_request(
        re.compile(r"^/records$"), method="POST"
    ).respond_with_json({"id": record_id, "pids": {}})
    # File upload slot + content + commit
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/files$"), method="POST"
    ).respond_with_json({"entries": []})
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/files/.+/content$"),
        method="PUT",
    ).respond_with_data("", status=200)
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/files/.+/commit$"),
        method="POST",
    ).respond_with_json({"key": "file", "status": "completed"})
    # Reserve a DOI on the draft – this is where the identifier actually comes
    # from in the #927 scenario
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/pids/doi$"), method="POST"
    ).respond_with_json({"pids": {"doi": {"identifier": reserved_doi}}})
    # Publish returns an EMPTY pids payload (the bug scenario)
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}/draft/actions/publish$"),
        method="POST",
    ).respond_with_json({"id": record_id, "pids": {}})
    # The published record echoes the minted DOI, recovered by the poll
    httpserver.expect_request(
        re.compile(rf"^/records/{record_id}$"), method="GET"
    ).respond_with_json(
        {"id": record_id, "pids": {"doi": {"identifier": reserved_doi}}}
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "project",
            ".",
            "--title",
            "Test project",
            "--name",
            "test-project",
        ]
    )
    subprocess.check_call(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/calkit/test-project.git",
        ]
    )
    calkit.releases.set_cff_authors(
        [{"first_name": "Alice", "last_name": "Smith", "affiliation": "SomeU"}]
    )
    subprocess.check_call(
        ["calkit", "update", "license", "--copyright-holder", "Some Person"]
    )
    # One-shot publish (no --draft) so the new.py publish/poll path runs
    subprocess.check_call(
        [
            "calkit",
            "new",
            "release",
            "--name",
            "v0.1.0",
            "--description",
            "First release.",
            "--no-github",
            "--no-push",
            "--verbose",
        ]
    )
    release = calkit.load_calkit_info()["releases"]["v0.1.0"]
    # Despite the empty pids in the publish response, the DOI is recovered
    assert release["doi"] == reserved_doi
    assert release["url"] == f"https://doi.org/{reserved_doi}"


def _setup_zenodo_sandbox_project(monkeypatch):
    """Shared setup for the live Zenodo sandbox tests.

    Skips unless the test is explicitly opted into via
    ``CALKIT_TEST_ZENODO_SANDBOX=1`` (so it never runs in CI -- GitHub Actions
    doesn't set that variable) and a sandbox token is available. Resolves the
    token (allowing it to live in a local ``.env``), points the client at the
    sandbox, and creates a project with authors and a license ready to be
    released. Must be called from within a ``tmp_dir`` test.
    """
    if os.getenv("CALKIT_TEST_ZENODO_SANDBOX") != "1":
        pytest.skip(
            "Live Zenodo sandbox test; set CALKIT_TEST_ZENODO_SANDBOX=1 "
            "(and provide a sandbox ZENODO_TOKEN) to run it"
        )
    # Allow the token to live in a local .env file (the usual way calkit
    # resolves credentials). The calkit subprocesses run in tmp_dir, outside
    # the repo, so their own load_dotenv() won't find it -- we load it here and
    # export it below so they inherit it.
    import dotenv

    dotenv.load_dotenv()
    token = (
        os.getenv("ZENODO_TOKEN")
        or os.getenv("CALKIT_TEST_ZENODO_TOKEN")
        or os.getenv("CALKIT_ZENODO_TOKEN")
    )
    if not token:
        pytest.skip(
            "No sandbox Zenodo token found; set ZENODO_TOKEN (or "
            "CALKIT_TEST_ZENODO_TOKEN) to a sandbox.zenodo.org token"
        )
    # Export the token as ZENODO_TOKEN so every calkit subprocess picks it up,
    # and make sure nothing forces us onto the production base URL.
    monkeypatch.setenv("ZENODO_TOKEN", token)
    monkeypatch.delenv("CALKIT_USE_PROD_FOR_TESTS", raising=False)
    monkeypatch.delenv("CALKIT_INVENIO_BASE_URL_ZENODO", raising=False)
    # Sanity check: in the test env we should be pointed at the sandbox
    assert (
        calkit.invenio.get_base_url("zenodo")
        == "https://sandbox.zenodo.org/api"
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "project",
            ".",
            "--title",
            "Test project",
            "--name",
            "test-project",
        ]
    )
    subprocess.check_call(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/calkit/test-project.git",
        ]
    )
    calkit.releases.set_cff_authors(
        [
            {
                "first_name": "Alice",
                "last_name": "Smith",
                "affiliation": "SomeU",
                "orcid": "0000-0001-2345-6789",
            },
            {
                "first_name": "Bob",
                "last_name": "Jones",
                "affiliation": None,
                "orcid": None,
            },
        ]
    )
    subprocess.check_call(
        ["calkit", "update", "license", "--copyright-holder", "Some Person"]
    )


def test_new_release_zenodo_sandbox(tmp_dir, monkeypatch):
    """Live integration test against the real Zenodo sandbox API.

    Unlike ``test_new_release`` (which mocks the Invenio API), this exercises
    the full release flow against ``sandbox.zenodo.org`` so we can catch
    regressions the mock can't -- e.g. metadata our client builds that the
    real API rejects. It is deliberately gated behind
    ``CALKIT_TEST_ZENODO_SANDBOX=1`` so it never runs in CI (GitHub Actions
    does not set that variable); it's only for occasional manual local
    verification.

    Requirements to run locally::

        CALKIT_TEST_ZENODO_SANDBOX=1
        ZENODO_TOKEN=<a sandbox.zenodo.org personal access token with the
                      deposit:write and deposit:actions scopes>

    The test only ever creates (and then deletes) a *draft* record -- it never
    publishes, because a published sandbox record cannot be removed via the
    API and would litter the account.
    """
    _setup_zenodo_sandbox_project(monkeypatch)
    record_id = None
    try:
        subprocess.check_call(
            [
                "calkit",
                "new",
                "release",
                "--name",
                "v0.1.0",
                "--description",
                "First release.",
                "--draft",
                "--no-github",
                "--verbose",
            ]
        )
        ck_info = calkit.load_calkit_info()
        assert "v0.1.0" in ck_info["releases"]
        release = ck_info["releases"]["v0.1.0"]
        record_id = release["record_id"]
        assert record_id is not None
        # A DOI should have been reserved for the draft
        assert release["doi"] is not None
        # The draft really exists on the sandbox with the metadata we sent;
        # fetching it confirms our client and the real API agree on shape
        draft = calkit.invenio.get(f"/records/{record_id}/draft")
        metadata = draft["metadata"]
        assert metadata["title"] == "Test project"
        # NOTE: our client POSTs the InvenioRDM metadata schema (creators with
        # person_or_org/given_name/family_name), but the Zenodo draft GET
        # endpoint echoes back the *legacy* Zenodo serialization, where each
        # creator is a "Last, First" name string. Asserting on the real shape
        # here is the whole point of this test -- the mock can't reveal it.
        creators = metadata["creators"]
        assert creators[0]["name"] == "Smith, Alice"
        assert creators[0]["affiliation"] == "SomeU"
        assert creators[1]["name"] == "Jones, Bob"
        # License and the GitHub related-identifier round-trip correctly
        assert metadata["license"]["id"] == "cc-by-4.0"
        related = metadata["related_identifiers"]
        assert (
            related[0]["identifier"]
            == "https://github.com/calkit/test-project"
        )
        # Reuploading the draft should also succeed against the real API
        subprocess.check_call(
            ["calkit", "update", "release", "--name", "v0.1.0", "--reupload"]
        )
    finally:
        # Always clean up the draft so we don't accumulate records on the
        # sandbox, even if an assertion above failed.
        if record_id is not None:
            try:
                calkit.invenio.delete(
                    f"/records/{record_id}/draft", as_json=False
                )
            except Exception as e:
                print(f"Warning: failed to clean up sandbox draft: {e}")


def test_new_release_zenodo_sandbox_publish(tmp_dir, monkeypatch):
    """Live test of the full *publish* path against the Zenodo sandbox.

    This is the companion to ``test_new_release_zenodo_sandbox``: instead of a
    draft, it runs a one-shot ``new release`` (no ``--draft``), which is the
    only path that exercises the DOI-minting logic this branch hardens --
    reserving a DOI on the draft, publishing, and then (because the publish
    action returns 202 and may not echo the DOI immediately) retrying a fetch
    of the published record and pulling the DOI out with
    ``invenio.extract_doi``.

    Same opt-in gate as the draft test (``CALKIT_TEST_ZENODO_SANDBOX=1``), so
    it never runs in CI. WARNING: unlike the draft test, this PUBLISHES a real
    sandbox record, which cannot be deleted via the API, so each run leaves one
    behind on the sandbox account. It is intentionally separate so the draft
    test can stay self-cleaning.
    """
    _setup_zenodo_sandbox_project(monkeypatch)
    # No --draft: reserve + publish + mint DOI in one shot. --no-push skips the
    # git push and GitHub release entirely.
    subprocess.check_call(
        [
            "calkit",
            "new",
            "release",
            "--name",
            "v0.1.0",
            "--description",
            "First release.",
            "--no-github",
            "--no-push",
            "--verbose",
        ]
    )
    ck_info = calkit.load_calkit_info()
    assert "v0.1.0" in ck_info["releases"]
    release = ck_info["releases"]["v0.1.0"]
    record_id = release["record_id"]
    assert record_id is not None
    # The minted DOI should have been resolved and saved (this is exactly what
    # the publish-path fix is about)
    doi = release["doi"]
    assert doi is not None
    assert doi.startswith("10.")
    print(f"Published sandbox record {record_id} with DOI {doi}")
    # The published record really exists and exposes the same DOI via the API,
    # confirming extract_doi agrees with the real published record
    record = calkit.invenio.get(f"/records/{record_id}")
    assert calkit.invenio.extract_doi(record) == doi
    # A Git tag for the release should have been created locally
    assert "v0.1.0" in [tag.name for tag in git.Repo().tags]


def test_new_release_is_runnable(tmp_dir, monkeypatch):
    # Provide a dummy Zenodo token so `new_release` can pass its early
    # token-validation step even in dry-run mode.
    monkeypatch.setenv("ZENODO_TOKEN", "test-token")
    subprocess.check_call(["calkit", "init"])
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "title": "Test project",
                "name": "test-project",
                "owner": "test-user",
                "git_repo_url": "https://github.com/test-user/test-project",
                "environments": {
                    "main": {
                        "kind": "uv-venv",
                        "path": "requirements.txt",
                        "prefix": ".venv",
                        "python": "3.13",
                    }
                },
                "pipeline": {
                    "stages": {
                        "get-data": {
                            "kind": "python-script",
                            "script_path": "get_data.py",
                            "environment": "main",
                            "outputs": ["results"],
                        }
                    }
                },
            },
            f,
        )
    # Authors live in CITATION.cff, the single source of truth
    calkit.releases.set_cff_authors(
        [
            {
                "first_name": "Alice",
                "last_name": "Smith",
                "affiliation": "SomeU",
                "orcid": "0000-0001-2345-6789",
            }
        ]
    )
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    with open("get_data.py", "w") as f:
        f.write("print('running running running')\n")
        f.write("import os\n")
        f.write("os.makedirs('results', exist_ok=True)\n")
        f.write("with open('results/data.txt', 'w') as f:\n")
        f.write("    f.write('hello world')\n")
    # Add a license
    subprocess.check_call(
        [
            "calkit",
            "update",
            "license",
            "-c",
            "Some Person",
        ]
    )
    out = subprocess.check_output(["calkit", "run"], text=True)
    assert "running running running" in out
    repo = git.Repo()
    repo.git.add(
        [
            "calkit.yaml",
            "dvc.yaml",
            "dvc.lock",
            "requirements.txt",
            "get_data.py",
        ]
    )
    repo.git.commit("-m", "Add pipeline for release test")
    # Run the pipeline again and make sure it's up to date
    out = subprocess.check_output(["calkit", "run"], text=True)
    assert "running running running" not in out
    out = subprocess.check_output(
        [
            "calkit",
            "new",
            "release",
            "--name",
            "v0.1.0",
            "--dry-run",
            "--description",
            "First release.",
            "--draft",
            "--no-github",
        ],
        text=True,
    )
    print(out)
    assert "running running running" not in out


def test_new_release_license_and_cff_authors(tmp_dir, monkeypatch):
    # Covers two edge cases via a dry-run release: detecting a standard
    # (non-Calkit) MIT license (regression for issue 919) and reading authors
    # from a CITATION.cff file when none are defined in calkit.yaml.
    monkeypatch.setenv("ZENODO_TOKEN", "test-token")
    subprocess.check_call(["calkit", "init"])
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "title": "Test project",
                "name": "test-project",
                "owner": "test-user",
                "git_repo_url": "https://github.com/test-user/test-project",
                "environments": {
                    "main": {
                        "kind": "uv-venv",
                        "path": "requirements.txt",
                        "prefix": ".venv",
                        "python": "3.13",
                    }
                },
                "pipeline": {
                    "stages": {
                        "get-data": {
                            "kind": "python-script",
                            "script_path": "get_data.py",
                            "environment": "main",
                            "outputs": ["results"],
                        }
                    }
                },
            },
            f,
        )
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    with open("get_data.py", "w") as f:
        f.write("import os\n")
        f.write("os.makedirs('results', exist_ok=True)\n")
        f.write("open('results/data.txt', 'w').write('hello world')\n")
    # Write a standard MIT license, which says "MIT License" (not "The MIT
    # License") and previously failed to be detected
    with open("LICENSE", "w") as f:
        f.write(
            "MIT License\n\nCopyright (c) 2026 Alice Smith\n\n"
            "Permission is hereby granted, free of charge, to any person "
            "obtaining a copy of this software and associated documentation "
            'files (the "Software"), to deal in the Software without '
            "restriction.\n"
        )
    # Declare authors only in CITATION.cff, not calkit.yaml
    with open("CITATION.cff", "w") as f:
        calkit.ryaml.dump(
            {
                "cff-version": "1.2.0",
                "title": "Test project",
                "authors": [
                    {
                        "family-names": "Smith",
                        "given-names": "Alice",
                        "orcid": "https://orcid.org/0000-0001-2345-6789",
                    }
                ],
            },
            f,
        )
    subprocess.check_call(["calkit", "run"])
    repo = git.Repo()
    repo.git.add(
        [
            "calkit.yaml",
            "dvc.yaml",
            "dvc.lock",
            "requirements.txt",
            "get_data.py",
            "LICENSE",
            "CITATION.cff",
        ]
    )
    repo.git.commit("-m", "Add pipeline for release test")
    out = subprocess.check_output(
        [
            "calkit",
            "new",
            "release",
            "--name",
            "v0.1.0",
            "--dry-run",
            "--draft",
            "--no-github",
        ],
        text=True,
    )
    print(out)
    assert "Detected license(s): mit" in out
    assert "Read 1 author(s) from CITATION.cff" in out
