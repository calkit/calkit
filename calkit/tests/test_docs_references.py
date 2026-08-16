"""Tests for the generated documentation references."""

from __future__ import annotations

import importlib.util
import os
import types

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="module")
def generator() -> types.ModuleType:
    # The generator is a script, not part of the package, and its name isn't
    # a valid identifier, so it can't simply be imported
    fpath = os.path.join(REPO_ROOT, "scripts", "generate-docs-references.py")
    spec = importlib.util.spec_from_file_location("docs_references", fpath)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pipeline_reference_documents_nested_types(
    generator: types.ModuleType,
) -> None:
    from calkit.models.pipeline import Stage

    fpath = os.path.join(REPO_ROOT, "docs", "pipeline", "index.md")
    with open(fpath, encoding="utf-8") as f:
        doc = f.read()
    stage_classes = [
        cls
        for cls in Stage.__subclasses__()
        if generator._kind_for_model_class(cls)
    ]
    nested = generator._collect_nested_models([Stage] + stage_classes)
    # Parameters like inputs and outputs are typed as objects whose properties
    # used to be named but never described, so every model reachable from a
    # stage needs a table of its own
    assert {cls.__name__ for cls in nested} >= {
        "InputsFromStageOutputs",
        "PathOutput",
        "StageIteration",
        "StageSchedulerOptions",
    }
    for cls in nested:
        assert f"#### `{cls.__name__}`" in doc, (
            f"{cls.__name__} is missing from the pipeline reference; "
            "regenerate it with 'make sync-docs'"
        )
        for name, field in cls.model_fields.items():
            assert f"`{field.alias or name}`" in doc
    # Allowable values must be spelled out, not just the type name
    assert "Literal['git', 'dvc', 'dvc-zip'] \\| None" in doc
    # Descriptions are what make the tables worth reading, so a model whose
    # fields have them must not render an empty column
    assert "Path to the output file or directory." in doc
    assert "Name of a stage whose outputs are inputs to this one." in doc


def test_descriptions_fall_back_to_the_base_class(
    generator: types.ModuleType,
) -> None:
    # JsonToLatexStage overrides environment only to give it a default, which
    # drops the description Stage declared
    markdown = generator.generate_stage_kinds_markdown()
    section = markdown.split("### `json-to-latex`")[1].split("###")[0]
    assert "Name of the environment in which to run this stage." in section
    # Environment subclasses do the same with kind, narrowing it to a single
    # value without restating what it's for
    markdown = generator.generate_environment_kinds_markdown()
    section = markdown.split("#### `docker`")[1].split("####")[0]
    assert "What kind of environment this is." in section
    assert "Name of the Docker image." in section


def test_system_lock_properties_are_documented(
    generator: types.ModuleType,
) -> None:
    from typing import get_args

    from calkit.environments import (
        SYSTEM_LOCK_PROPERTIES,
        SYSTEM_LOCK_PROPERTY_DESCRIPTIONS,
    )
    from calkit.models.core import SystemLockProperty

    # Someone deciding what to lock needs to know what's on offer, and
    # 'list[Literal[...]]' crammed into a type column is not that
    assert set(SYSTEM_LOCK_PROPERTY_DESCRIPTIONS) == set(
        SYSTEM_LOCK_PROPERTIES
    ), "every lockable property needs a description, and vice versa"
    assert set(get_args(SystemLockProperty)) == set(SYSTEM_LOCK_PROPERTIES)
    fpath = os.path.join(REPO_ROOT, "docs", "environments.md")
    with open(fpath, encoding="utf-8") as f:
        doc = f.read()
    block = doc.split(generator.SYSTEM_LOCK_START)[1].split(
        generator.SYSTEM_LOCK_END
    )[0]
    for prop, description in SYSTEM_LOCK_PROPERTY_DESCRIPTIONS.items():
        assert f"`{prop}`" in block, (
            f"'{prop}' is missing from the environments reference; "
            "regenerate it with 'make sync-docs'"
        )
        assert description.split(".")[0] in block, (
            f"'{prop}' is listed without its description"
        )
    # A property only one platform can supply says so, since locking it
    # anywhere else is an error rather than a silent no-op
    assert "macOS only" in block
