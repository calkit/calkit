"""Tests for ``calkit.markdown``."""

from __future__ import annotations

import pytest

from calkit.markdown import (
    MarkdownParseError,
    parse_attrs,
    parse_markdown,
)


def test_parse_attrs():
    assert parse_attrs("name=example environment=main") == {
        "name": "example",
        "environment": "main",
    }
    # Values are YAML flow scalars, so structure works without a bespoke
    # grammar, spaces and all
    assert parse_attrs("outputs=[{path: sup.png, storage: git}]") == {
        "outputs": [{"path": "sup.png", "storage": "git"}]
    }
    assert parse_attrs("inputs=[a.csv, b.csv] name=x") == {
        "inputs": ["a.csv", "b.csv"],
        "name": "x",
    }
    # A bare key is a flag
    assert parse_attrs("name=x always_run") == {
        "name": "x",
        "always_run": True,
    }
    assert parse_attrs('description="a thing with spaces"') == {
        "description": "a thing with spaces"
    }
    assert parse_attrs("") == {}
    with pytest.raises(ValueError, match="Duplicate"):
        parse_attrs("name=a name=b")
    with pytest.raises(ValueError, match="no value"):
        parse_attrs("name= environment=main")
    with pytest.raises(ValueError, match="Unbalanced"):
        parse_attrs("outputs=[a.png")


def test_unannotated_fences_are_inert():
    text = """
# Title

```sh
uv add something
```

```python
print("just an example")
```
"""
    assert parse_markdown(text) == []


def test_parse_stage_fence():
    text = """
Some prose.

```python calkit stage name=example environment=main outputs=[fig.png]
print("hi")
```
"""
    (block,) = parse_markdown(text)
    assert block.kind == "stage"
    assert block.language == "python"
    assert block.name == "example"
    assert block.attrs["outputs"] == ["fig.png"]
    assert block.content == 'print("hi")'
    assert block.source == "fence"


def test_blocks_split_by_name():
    text = """
```python calkit stage name=ex environment=main
import os
```

Prose in between.

```python
print("not part of it")
```

```python calkit stage name=ex
print(os.getcwd())
```
"""
    blocks = parse_markdown(text)
    assert [b.name for b in blocks] == ["ex", "ex"]
    assert blocks[0].content == "import os"
    assert blocks[1].content == "print(os.getcwd())"


def test_comment_directive_over_list():
    text = """
The `main` environment needs:

<!-- calkit environment name=main python=3.13 -->
- numpy
- matplotlib
- pandas

More prose.
"""
    (block,) = parse_markdown(text)
    assert block.kind == "environment"
    assert block.attrs == {"name": "main", "python": 3.13}
    assert block.content == "numpy\nmatplotlib\npandas"
    assert block.source == "list"


def test_comment_directive_over_fence():
    text = """
<!-- calkit environment name=main kind=uv-venv -->
```
numpy==1.0
-e .
```
"""
    (block,) = parse_markdown(text)
    assert block.kind == "environment"
    assert block.attrs == {"name": "main", "kind": "uv-venv"}
    assert block.content == "numpy==1.0\n-e ."


def test_comment_directive_merges_with_fence():
    text = """
<!-- calkit stage
     inputs=[data/one.csv, data/two.csv, data/three.csv] -->
```python calkit stage name=ex environment=main
pass
```
"""
    (block,) = parse_markdown(text)
    assert block.name == "ex"
    assert block.attrs["environment"] == "main"
    assert block.attrs["inputs"] == [
        "data/one.csv",
        "data/two.csv",
        "data/three.csv",
    ]


def test_comment_directive_conflict_is_an_error():
    text = """
<!-- calkit stage name=a -->
```python calkit stage name=b
pass
```
"""
    with pytest.raises(MarkdownParseError, match="set in both"):
        parse_markdown(text)


def test_longer_fence_contains_shorter_ones():
    # This is how a Markdown file documents the feature without declaring
    # the examples it shows
    text = """
Annotate a block like this:

````md
```python calkit stage name=not-real environment=main
print("documentation, not a stage")
```
````
"""
    assert parse_markdown(text) == []


def test_annotated_outer_fence_keeps_inner_content():
    text = """
````python calkit stage name=ex environment=main
```
````
"""
    (block,) = parse_markdown(text)
    assert block.content == "```"


def test_ordinary_html_comments_are_ignored():
    text = """
<!-- just a note -->
Some prose.

<!-- a
multiline
note -->
"""
    assert parse_markdown(text) == []


def test_unknown_directive_is_an_error():
    text = """
```python calkit stagg name=x
pass
```
"""
    with pytest.raises(MarkdownParseError, match="must name a directive"):
        parse_markdown(text)


def test_dangling_directive_is_an_error():
    text = """
<!-- calkit environment name=main -->

Just prose, no block.
"""
    with pytest.raises(MarkdownParseError, match="must be followed by"):
        parse_markdown(text)


def test_error_reports_path_and_line():
    text = "\n\n\n```python calkit stage name=a name=b\npass\n```\n"
    with pytest.raises(MarkdownParseError) as exc:
        parse_markdown(text, path="README.md")
    assert "README.md:4" in str(exc.value)


def test_extract_stages_concatenates_by_name():
    from calkit.markdown import extract_stages

    text = """
```python calkit stage name=ex environment=main
import os
```

Prose.

```python calkit stage name=ex outputs=[fig.png]
print(os.getcwd())
```

```python calkit stage name=other environment=main
pass
```
"""
    specs = extract_stages(parse_markdown(text), "README.md")
    assert sorted(specs) == ["ex", "other"]
    ex = specs["ex"]
    assert ex.content == "import os\n\nprint(os.getcwd())"
    # Attributes union across the stage's blocks
    assert ex.attrs == {"environment": "main", "outputs": ["fig.png"]}
    assert ex.script_path == ".calkit/markdown/README/ex.py"
    assert ex.stage_kind == "python-script"


def test_extract_stages_nested_markdown_path():
    from calkit.markdown import extract_stages

    text = "```python calkit stage name=ex environment=main\npass\n```\n"
    specs = extract_stages(parse_markdown(text), "docs/guide.md")
    assert specs["ex"].script_path == ".calkit/markdown/docs/guide/ex.py"


def test_extract_stages_rejects_mixed_languages():
    from calkit.markdown import extract_stages

    text = """
```python calkit stage name=ex environment=main
pass
```
```sh calkit stage name=ex
echo hi
```
"""
    with pytest.raises(MarkdownParseError, match="mixes languages"):
        extract_stages(parse_markdown(text), "README.md")


def test_extract_stages_rejects_conflicting_attrs():
    from calkit.markdown import extract_stages

    text = """
```python calkit stage name=ex environment=main
pass
```
```python calkit stage name=ex environment=other
pass
```
"""
    with pytest.raises(MarkdownParseError, match="conflicting"):
        extract_stages(parse_markdown(text), "README.md")


def test_extract_stages_requires_a_name():
    from calkit.markdown import extract_stages

    text = "```python calkit stage environment=main\npass\n```\n"
    with pytest.raises(MarkdownParseError, match="must declare a name"):
        extract_stages(parse_markdown(text), "README.md")


def test_extract_stages_rejects_unrunnable_language():
    from calkit.markdown import extract_stages

    text = "```yaml calkit stage name=ex environment=main\na: 1\n```\n"
    with pytest.raises(MarkdownParseError, match="can't run"):
        extract_stages(parse_markdown(text), "README.md")


def test_write_stage_scripts_only_rewrites_on_change(tmp_path):
    from calkit.markdown import extract_stages, write_stage_scripts

    text = "```python calkit stage name=ex environment=main\nprint(1)\n```\n"
    specs = extract_stages(parse_markdown(text), "README.md")
    assert write_stage_scripts(specs, wdir=str(tmp_path)) == [
        ".calkit/markdown/README/ex.py"
    ]
    fpath = tmp_path / ".calkit" / "markdown" / "README" / "ex.py"
    assert fpath.read_text() == "print(1)\n"
    # A stage script is a dependency, so an unchanged one must not be
    # touched or the stage would rerun for nothing
    mtime = fpath.stat().st_mtime_ns
    assert write_stage_scripts(specs, wdir=str(tmp_path)) == []
    assert fpath.stat().st_mtime_ns == mtime


def test_extract_and_resolve_environments():
    from calkit.markdown import (
        extract_environments,
        extract_stages,
        resolve_environments,
    )

    text = """
The `main` environment needs:

<!-- calkit environment name=main python=3.13 -->
- numpy
- matplotlib

And a second one, with pins the list form would make awkward:

<!-- calkit environment name=pinned -->
```
pandas==2.0.0
-e .
```

```python calkit stage name=demo environment=main
pass
```
"""
    blocks = parse_markdown(text)
    envs = resolve_environments(
        extract_environments(blocks, "README.md"),
        extract_stages(blocks, "README.md"),
        "README.md",
    )
    assert envs["main"]["kind"] == "uv-venv"
    assert envs["main"]["path"] == ".calkit/envs/main/requirements.txt"
    assert envs["main"]["python"] == "3.13"
    assert envs["main"]["_spec_content"] == "numpy\nmatplotlib"
    # A fence is kept verbatim, since it's the escape hatch for whatever
    # the list form can't say
    assert envs["pinned"]["_spec_content"] == "pandas==2.0.0\n-e ."


def test_resolve_environments_infers_kind_from_language():
    """An R or Julia README needn't spell out its environment's kind."""
    from calkit.markdown import (
        extract_environments,
        extract_stages,
        resolve_environments,
    )

    for language, kind, filename in [
        ("r", "renv", "DESCRIPTION"),
        ("julia", "julia", "Project.toml"),
        ("python", "uv-venv", "requirements.txt"),
    ]:
        text = (
            "<!-- calkit environment name=main -->\n"
            "- somepkg\n\n"
            f"```{language} calkit stage name=demo\n"
            "x\n```\n"
        )
        blocks = parse_markdown(text)
        envs = resolve_environments(
            extract_environments(blocks, "README.md"),
            extract_stages(blocks, "README.md"),
            "README.md",
            default_env="main",
        )
        assert envs["main"]["kind"] == kind
        assert envs["main"]["path"] == f".calkit/envs/main/{filename}"
        # The package list is rendered the way that toolchain spells it
        assert "somepkg" in envs["main"]["_spec_content"]


def test_resolve_environments_mixed_languages_needs_explicit_kind():
    from calkit.markdown import (
        extract_environments,
        extract_stages,
        resolve_environments,
    )

    text = (
        "<!-- calkit environment name=main -->\n- pkg\n\n"
        "```python calkit stage name=a environment=main\npass\n```\n\n"
        "```r calkit stage name=b environment=main\nx\n```\n"
    )
    blocks = parse_markdown(text)
    with pytest.raises(MarkdownParseError, match="more than one language"):
        resolve_environments(
            extract_environments(blocks, "README.md"),
            extract_stages(blocks, "README.md"),
            "README.md",
        )


def test_extract_environments_errors():
    from calkit.markdown import extract_environments

    with pytest.raises(MarkdownParseError, match="must declare a name"):
        extract_environments(
            parse_markdown("<!-- calkit environment -->\n- numpy\n"),
            "README.md",
        )
    with pytest.raises(MarkdownParseError, match="more than once"):
        extract_environments(
            parse_markdown(
                "<!-- calkit environment name=a -->\n- numpy\n\n"
                "<!-- calkit environment name=a -->\n- scipy\n"
            ),
            "README.md",
        )
    with pytest.raises(MarkdownParseError, match="must be one of"):
        extract_environments(
            parse_markdown(
                "<!-- calkit environment name=a kind=conda -->\n- numpy\n"
            ),
            "README.md",
        )
    with pytest.raises(MarkdownParseError, match="unrecognized attribute"):
        extract_environments(
            parse_markdown(
                "<!-- calkit environment name=a nope=1 -->\n- numpy\n"
            ),
            "README.md",
        )


def test_expand_ck_info(tmp_path, monkeypatch):
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "<!-- calkit environment name=main python=3.12 -->\n"
        "- numpy\n\n"
        "```python calkit stage name=demo outputs=[out.txt]\n"
        "pass\n```\n"
    )
    ck_info = {"pipeline": {"stages": {"README.md": {"kind": "markdown"}}}}
    result = expand_ck_info(ck_info)
    # The input is untouched, so a caller that writes calkit.yaml back can't
    # persist derived entries by accident
    assert ck_info == {
        "pipeline": {"stages": {"README.md": {"kind": "markdown"}}}
    }
    stages = result.ck_info["pipeline"]["stages"]
    assert list(stages) == ["README.md/demo"]
    stage = stages["README.md/demo"]
    assert stage["kind"] == "python-script"
    assert stage["script_path"] == ".calkit/markdown/README/demo.py"
    assert stage["outputs"] == ["out.txt"]
    # A file declaring exactly one environment doesn't have to name it on
    # every block
    assert stage["environment"] == "main"
    assert result.ck_info["environments"]["main"]["kind"] == "uv-venv"
    assert result.environments["main"]["python"] == "3.12"
    assert result.environment_sources["main"] == "README.md"
    assert (tmp_path / ".calkit/envs/main/requirements.txt").read_text() == (
        "numpy\n"
    )


def test_expand_ck_info_env_conflict(tmp_path, monkeypatch):
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "<!-- calkit environment name=main -->\n- numpy\n\n"
        "```python calkit stage name=demo\npass\n```\n"
    )
    ck_info = {
        "environments": {"main": {"kind": "conda", "path": "environment.yml"}},
        "pipeline": {"stages": {"README.md": {"kind": "markdown"}}},
    }
    with pytest.raises(ValueError, match="only be defined in one place"):
        expand_ck_info(ck_info)
    # An identical entry is this definition written back on an earlier
    # compile, not a competing one
    ck_info["environments"]["main"] = {
        "kind": "uv-venv",
        "path": ".calkit/envs/main/requirements.txt",
    }
    assert expand_ck_info(ck_info).environments["main"]["kind"] == "uv-venv"


def test_detect_environments_merges_by_language():
    """One environment per language, not one per code block.

    A README's examples are variations on the same setup, so a virtualenv
    per block would be churn for nothing.
    """
    from calkit.markdown import detect_environments, extract_stages

    text = (
        "```python calkit stage name=a\nimport numpy as np\nimport pandas\n```\n\n"
        "```python calkit stage name=b\nimport matplotlib\nimport numpy\n```\n\n"
        "```r calkit stage name=c\nlibrary(dplyr)\n```\n\n"
        "```sh calkit stage name=d\necho hi\n```\n"
    )
    specs = extract_stages(parse_markdown(text), "README.md")
    envs, assignments = detect_environments(specs, "README.md")
    # Both Python stages share one environment, with dependencies merged
    # and de-duplicated
    assert assignments == {"a": "readme-py", "b": "readme-py", "c": "readme-r"}
    assert envs["readme-py"]["kind"] == "uv-venv"
    assert envs["readme-py"]["_spec_content"].split() == [
        "numpy",
        "pandas",
        "matplotlib",
    ]
    assert envs["readme-r"]["kind"] == "renv"
    assert "dplyr" in envs["readme-r"]["_spec_content"]
    # Shell has no imports to read, so it keeps whatever it was given
    assert "d" not in assignments


def test_detect_environments_single_language_is_unsuffixed():
    from calkit.markdown import detect_environments, extract_stages

    text = "```python calkit stage name=a\nimport numpy\n```\n"
    specs = extract_stages(parse_markdown(text), "docs/guide.md")
    envs, assignments = detect_environments(specs, "docs/guide.md")
    assert list(envs) == ["guide"]
    assert assignments == {"a": "guide"}


def test_detect_environments_skips_declared_and_avoids_collisions():
    from calkit.markdown import detect_environments, extract_stages

    text = (
        "```python calkit stage name=a environment=mine\nimport numpy\n```\n\n"
        "```python calkit stage name=b\nimport scipy\n```\n"
    )
    specs = extract_stages(parse_markdown(text), "README.md")
    envs, assignments = detect_environments(
        specs, "README.md", existing_env_names=["readme"]
    )
    # The stage that named an environment is left alone
    assert assignments == {"b": "readme-2"}
    assert list(envs) == ["readme-2"]
    # A file whose stages all name an environment needs nothing detected
    envs, assignments = detect_environments(
        specs, "README.md", default_env="main"
    )
    assert envs == {} and assignments == {}


def test_output_blocks_are_never_extracted():
    """An output block must not become part of its stage's script.

    If it did, injecting output would change the script, which would make
    the stage stale, which would rerun it, which would inject again.
    """
    from calkit.markdown import extract_stages

    text = (
        "```python calkit stage name=a\nprint('hi')\n```\n\n"
        "```text calkit output stage=a\nhi\n```\n"
    )
    specs = extract_stages(parse_markdown(text), "README.md")
    assert list(specs) == ["a"]
    assert specs["a"].content == "print('hi')"


def test_set_output_blocks():
    from calkit.markdown import set_output_blocks

    text = (
        "# Demo\n\n"
        "```python calkit stage name=a\nprint('x')\n```\n\n"
        "```text calkit output stage=a\nstale\n```\n\n"
        "```text\nan ordinary block\n```\n"
    )
    out, changed = set_output_blocks(text, {"a": "x\ny"})
    assert changed
    assert "```text calkit output stage=a\nx\ny\n```" in out
    # Blocks that aren't outputs are untouched
    assert "```text\nan ordinary block\n```" in out
    # Writing the same output again changes nothing
    assert set_output_blocks(out, {"a": "x\ny"}) == (out, False)
    # A stage that ran but printed nothing empties its block rather than
    # leaving a stale value behind
    emptied, changed = set_output_blocks(out, {"a": ""})
    assert changed
    assert "```text calkit output stage=a\n```" in emptied
    # A stage with no output block is simply not shown
    assert set_output_blocks(text, {"nonexistent": "z"}) == (text, False)


def test_set_output_blocks_ignores_nested_fences():
    from calkit.markdown import set_output_blocks

    text = (
        "````md\n```text calkit output stage=a\nnot a real block\n```\n````\n"
    )
    assert set_output_blocks(text, {"a": "new"}) == (text, False)
