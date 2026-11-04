"""Tests for ``resources``."""

import os
import re

import pytest

import calkit
import calkit.resources


def test_resources(monkeypatch):
    resources_dir = calkit.resources.get_dir()
    assert os.path.isdir(resources_dir)
    spec = calkit.resources.load_json(
        "devcontainer", calkit.resources.DEVCONTAINER_FNAME
    )
    # The committed spec must match what the VS Code config generates, else
    # the two would drift; run `make sync-resources` if this fails
    assert spec == calkit.resources.render_devcontainer_spec()
    assert spec["image"].startswith("ghcr.io/calkit/devcontainer")
    settings = calkit.resources.load_json("vscode", "settings.json")
    extensions = calkit.resources.load_json("vscode", "extensions.json")[
        "recommendations"
    ]
    customizations = spec["customizations"]["vscode"]
    for key, value in settings.items():
        assert customizations["settings"][key] == value
    assert customizations["extensions"] == extensions
    # Extension IDs are 'publisher.name', and a typo in one means it silently
    # never gets installed
    assert len(set(extensions)) == len(extensions)
    for ext in extensions:
        assert re.fullmatch(r"[\w-]+\.[\w-]+", ext), ext
    # The VS Code settings land in a user's project, so they mustn't override
    # personal preferences; those settings belong in the dev container's
    # base.json, which only applies inside the container
    for key in settings:
        assert not key.startswith(("workbench.colorTheme", "window."))
    # Only the generated keys come from the VS Code config, so anything else
    # the base customizes survives being merged with it
    real_load_json = calkit.resources.load_json

    def load_json_with_extra_customization(*relpath):
        data = real_load_json(*relpath)
        if relpath[-1] == "base.json":
            data["customizations"]["vscode"]["snippets"] = ["python"]
        return data

    monkeypatch.setattr(
        calkit.resources, "load_json", load_json_with_extra_customization
    )
    merged = calkit.resources.render_devcontainer_spec()["customizations"][
        "vscode"
    ]
    assert merged["snippets"] == ["python"]
    assert merged["extensions"] == extensions
    assert merged["settings"] == customizations["settings"]


def test_github_actions_workflow(tmp_path):
    workflow = calkit.ryaml.load(
        calkit.resources.read_text(
            "github-actions", calkit.resources.GITHUB_ACTIONS_FNAME
        )
    )
    steps = workflow["jobs"]["main"]["steps"]
    assert any(
        step.get("uses") == calkit.resources.ACTION_REF for step in steps
    )
    # The action needs these to push results and to exchange an OIDC token
    # for a Calkit one
    assert workflow["permissions"]["contents"] == "write"
    assert workflow["permissions"]["id-token"] == "write"
    # Released versions get pinned to a tag that exists in this repo; dev
    # versions have no tag to point at, so they stay on main
    pinned = calkit.resources.render_github_actions_workflow(version="1.2.3")
    assert "uses: calkit/calkit/actions/run@v1.2.3" in pinned
    assert calkit.resources.ACTION_REF not in pinned
    unpinned = calkit.resources.render_github_actions_workflow(
        version="1.2.3.dev0+g21c9bb93"
    )
    assert calkit.resources.ACTION_REF in unpinned
    # A project's workflow can be repinned in place, at whatever ref and in
    # whatever style it was written, including the action's previous home,
    # without touching anything else in it
    for uses in [
        "      - uses: calkit/run-action@v2\n",
        '      - uses: "calkit/calkit/actions/run@v0.1.0"\n',
        "        uses: calkit/calkit/actions/run@main\n",
    ]:
        custom = "# Custom\njobs:\n  main:\n    steps:\n" + uses
        assert calkit.resources.uses_run_action(custom)
        updated = calkit.resources.set_action_ref(custom, version="1.2.3")
        assert "calkit/calkit/actions/run@v1.2.3" in updated
        assert "run-action" not in updated
        assert updated.startswith("# Custom\n")
        assert len(updated.splitlines()) == len(custom.splitlines())
    # Steps that use other actions, or mention the action outside a ref,
    # must be left alone
    other = "      - uses: actions/checkout@v4\n# calkit/run-action@v2\n"
    assert not calkit.resources.uses_run_action(other)
    assert calkit.resources.set_action_ref(other, version="1.2.3") == other
    # Whether a project's workflow is still the example is what decides if
    # it gets replaced wholesale or only repinned, so the pin itself, and
    # line endings Git may have translated, can't affect that
    assert calkit.resources.is_default_github_actions_workflow(pinned)
    assert calkit.resources.is_default_github_actions_workflow(
        unpinned.replace("\n", "\r\n")
    )
    assert not calkit.resources.is_default_github_actions_workflow(
        pinned + "\n      - run: echo custom\n"
    )
    # Its triggers can be replaced, leaving the rest as it was, given as
    # event names or GitHub's mapping
    on_demand = calkit.resources.render_github_actions_workflow(
        on=["workflow_dispatch"]
    )
    assert calkit.ryaml.load(on_demand)["on"] == {"workflow_dispatch": None}
    assert "\non:\n  workflow_dispatch:\n\npermissions:" in on_demand
    default = calkit.resources.render_github_actions_workflow()
    assert on_demand.replace("  workflow_dispatch:\n", "") == default.replace(
        "  push:\n    branches:\n      - main\n  pull_request:\n"
        "  workflow_dispatch:\n",
        "",
    )
    assert not calkit.resources.is_default_github_actions_workflow(on_demand)
    for on, expected in [
        ("push", {"push": None}),
        (["push", "pull_request"], {"push": None, "pull_request": None}),
        ({"push": {"branches": ["main"]}}, {"push": {"branches": ["main"]}}),
    ]:
        txt = calkit.resources.set_workflow_triggers(on_demand, on)
        assert calkit.ryaml.load(txt)["on"] == expected
    # Even when a YAML 1.1 writer quoted the key
    quoted = calkit.resources.set_workflow_triggers(
        "'on': push\njobs: {}\n", "workflow_dispatch"
    )
    assert calkit.ryaml.load(quoted) == {
        "on": {"workflow_dispatch": None},
        "jobs": {},
    }
    # Whether a workflow can be started, however its triggers are written
    for txt, can in [
        (pinned, True),
        (on_demand, True),
        ("on: workflow_dispatch\n", True),
        ("on: [push, workflow_dispatch]\n", True),
        ("'on':\n  push:\n", False),
        ("on: push\n", False),
        ("jobs: {}\n", False),
        ("{{ not yaml\n", False),
        ("just text\n", False),
        ("- on\n", False),
    ]:
        assert calkit.resources.can_start_workflow(txt) is can, txt
    # Every workflow that runs the action is found, in name order, but not
    # others
    assert calkit.resources.find_run_workflows(str(tmp_path)) == []
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "tests.yml").write_text(other)
    (workflows_dir / "run.yaml").write_text(pinned)
    (workflows_dir / "on-demand.yml").write_text(on_demand)
    (workflows_dir / "notes.txt").write_text(pinned)
    # Nor symlinks, which could point anywhere, or files too big to be one
    outside = tmp_path / "outside.yml"
    outside.write_text(pinned)
    (workflows_dir / "link.yml").symlink_to(outside)
    (workflows_dir / "huge.yml").write_text(
        pinned + "#" * calkit.resources.MAX_WORKFLOW_BYTES
    )
    assert calkit.resources.find_run_workflows(str(tmp_path)) == [
        ("on-demand.yml", on_demand),
        ("run.yaml", pinned),
    ]
    # A workflows folder that's a symlink out of the project is skipped too
    other_project = tmp_path / "other"
    (other_project / ".github").mkdir(parents=True)
    (other_project / ".github" / "workflows").symlink_to(workflows_dir)
    assert calkit.resources.find_run_workflows(str(other_project)) == []
    # The bundled copy is generated from the action's own example, which is
    # only present in the repo, not in an installed package
    repo_copy = os.path.join(
        os.path.dirname(os.path.dirname(calkit.resources.get_dir())),
        "actions",
        "run",
        calkit.resources.GITHUB_ACTIONS_FNAME,
    )
    if not os.path.isfile(repo_copy):
        pytest.skip("Not running from a repo checkout")
    with open(repo_copy) as f:
        assert f.read() == calkit.resources.read_text(
            "github-actions", calkit.resources.GITHUB_ACTIONS_FNAME
        )
    # Everything the workflow does with the action is defined by it
    action_path = os.path.join(os.path.dirname(repo_copy), "action.yml")
    with open(action_path) as f:
        action = calkit.ryaml.load(f)
    step = next(
        s for s in steps if s.get("uses") == calkit.resources.ACTION_REF
    )
    for name in step.get("with", {}):
        assert name in action["inputs"]


def test_devcontainer_image_sources():
    resources_dir = calkit.resources.get_dir()
    devcontainer_dir = os.path.join(resources_dir, "devcontainer")
    with open(os.path.join(devcontainer_dir, "Dockerfile")) as f:
        dockerfile = f.read()
    scripts = os.listdir(os.path.join(devcontainer_dir, "scripts"))
    assert scripts
    for fname in scripts:
        assert f"COPY scripts/{fname}" in dockerfile
    # Every lifecycle hook the spec calls must be one of those scripts
    spec = calkit.resources.load_json(
        "devcontainer", calkit.resources.DEVCONTAINER_FNAME
    )
    hooks = [
        v
        for k, v in spec.items()
        if k.endswith("Command") and "$INIT_SCRIPTS_DIR" in str(v)
    ]
    assert hooks
    for hook in hooks:
        assert hook.split("$INIT_SCRIPTS_DIR/")[-1].strip() in scripts
