"""Tests for ``resources``."""

import os
import re

import calkit.resources


def test_resources():
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
