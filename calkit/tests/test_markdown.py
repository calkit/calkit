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
    assert ex.script_path == ".calkit/markdown/README.md/ex.py"
    assert ex.stage_kind == "python-script"


def test_extract_stages_nested_markdown_path():
    from calkit.markdown import extract_stages

    text = "```python calkit stage name=ex environment=main\npass\n```\n"
    specs = extract_stages(parse_markdown(text), "docs/guide.md")
    assert specs["ex"].script_path == ".calkit/markdown/docs/guide.md/ex.py"


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
        ".calkit/markdown/README.md/ex.py"
    ]
    fpath = tmp_path / ".calkit" / "markdown" / "README.md" / "ex.py"
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

<!-- calkit environment name=pinned kind=uv-venv -->
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
    # Python defaults to uv, whose lock is nicer than uv-venv's
    assert envs["main"]["kind"] == "uv"
    assert envs["main"]["path"] == ".calkit/envs/main/pyproject.toml"
    # A uv environment has no 'python' field; the version goes into the
    # pyproject.toml the spec is rendered into
    assert "python" not in envs["main"]
    assert "3.13" in envs["main"]["_spec_content"]
    assert "numpy" in envs["main"]["_spec_content"]
    assert "matplotlib" in envs["main"]["_spec_content"]
    # A fence is written verbatim, so a requirements-style list has to say
    # which kind it is
    assert envs["pinned"]["kind"] == "uv-venv"
    # A fence is kept verbatim, since it's the escape hatch for whatever
    # the list form can't say
    assert envs["pinned"]["_spec_content"] == "pandas==2.0.0\n-e ."


def test_resolve_environments_infers_kind_from_language():
    # An R or Julia README needn't spell out its environment's kind.
    from calkit.markdown import (
        extract_environments,
        extract_stages,
        resolve_environments,
    )

    for language, kind, filename, extra in [
        ("r", "renv", "DESCRIPTION", ""),
        # Calkit requires a version for Julia environments
        ("julia", "julia", "Project.toml", " julia=1.12"),
        ("python", "uv", "pyproject.toml", ""),
    ]:
        text = (
            f"<!-- calkit environment name=main{extra} -->\n"
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
                "<!-- calkit environment name=a kind=docker -->\n- numpy\n"
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
    ck_info = {
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"}
            }
        }
    }
    result = expand_ck_info(ck_info)
    # The input is untouched, so a caller that writes calkit.yaml back can't
    # persist derived entries by accident
    assert ck_info == {
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"}
            }
        }
    }
    stages = result.ck_info["pipeline"]["stages"]
    assert list(stages) == ["README.md/demo"]
    stage = stages["README.md/demo"]
    assert stage["kind"] == "python-script"
    assert stage["script_path"] == ".calkit/markdown/README.md/demo.py"
    assert stage["outputs"] == ["out.txt"]
    # A file declaring exactly one environment doesn't have to name it on
    # every block
    assert stage["environment"] == "main"
    assert result.ck_info["environments"]["main"]["kind"] == "uv"
    assert result.environment_sources["main"] == "README.md"
    spec = (tmp_path / ".calkit/envs/main/pyproject.toml").read_text()
    assert "numpy" in spec and "3.12" in spec


def test_expand_ck_info_env_conflict(tmp_path, monkeypatch):
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "<!-- calkit environment name=main -->\n- numpy\n\n"
        "```python calkit stage name=demo\npass\n```\n"
    )
    ck_info = {
        "environments": {"main": {"kind": "conda", "path": "environment.yml"}},
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"}
            }
        },
    }
    with pytest.raises(ValueError, match="only be defined in one place"):
        expand_ck_info(ck_info)
    # An identical entry is this definition written back on an earlier
    # compile, not a competing one
    ck_info["environments"]["main"] = {
        "kind": "uv",
        "path": ".calkit/envs/main/pyproject.toml",
        "description": (
            "Generated from README.md. Changes made here will be overwritten."
        ),
    }
    assert expand_ck_info(ck_info).environments["main"]["kind"] == "uv"


def test_detect_environments_merges_by_language():
    # One environment per language, not one per code block.
    #
    # A README's examples are variations on the same setup, so a virtualenv
    # per block would be churn for nothing.
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
    assert envs["readme-py"]["kind"] == "uv"
    for dep in ["numpy", "pandas", "matplotlib"]:
        assert dep in envs["readme-py"]["_spec_content"]
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
    # An output block must not become part of its stage's script.
    #
    # If it did, injecting output would change the script, which would make
    # the stage stale, which would rerun it, which would inject again.
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


def test_extract_outputs():
    from calkit.markdown import extract_outputs

    text = (
        "```python calkit stage name=a\nprint('x')\n```\n\n"
        "```text calkit output stage=a\nx\n```\n"
    )
    assert extract_outputs(parse_markdown(text), "README.md") == {"a": "x"}
    with pytest.raises(MarkdownParseError, match="must name the stage"):
        extract_outputs(
            parse_markdown("```text calkit output\nx\n```\n"), "README.md"
        )
    with pytest.raises(MarkdownParseError, match="more than one output"):
        extract_outputs(
            parse_markdown(
                "```text calkit output stage=a\nx\n```\n\n"
                "```text calkit output stage=a\ny\n```\n"
            ),
            "README.md",
        )


def test_expand_ck_info_output_cache_is_an_input(tmp_path, monkeypatch):
    # A stage depends on its output block, so editing it makes it stale.
    #
    # The cache can't be an output: injection happens after the pipeline
    # runs, so nothing the stage command itself does would satisfy one.
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "```python calkit stage name=a environment=main\nprint('x')\n```\n\n"
        "```text calkit output stage=a\nx\n```\n\n"
        "```python calkit stage name=b environment=main\npass\n```\n"
    )
    ck_info = {
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"}
            }
        }
    }
    result = expand_ck_info(ck_info)
    cache = ".calkit/markdown/outputs/README.md/a.txt"
    stages = result.ck_info["pipeline"]["stages"]
    assert stages["README.md/a"]["inputs"] == [cache]
    assert result.output_cache_paths == {"README.md/a": cache}
    # The cache holds exactly what the block says
    assert (tmp_path / cache).read_text() == "x\n"
    # A stage with no output block gets no such input
    assert stages["README.md/b"].get("inputs", []) == []


def test_expand_ck_info_rejects_output_for_unknown_stage(
    tmp_path, monkeypatch
):
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "```python calkit stage name=a environment=main\npass\n```\n\n"
        "```text calkit output stage=typo\nx\n```\n"
    )
    ck_info = {
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"}
            }
        }
    }
    with pytest.raises(ValueError, match="does not declare"):
        expand_ck_info(ck_info)


def test_expand_ck_info_prunes_orphaned_derived_files(tmp_path, monkeypatch):
    # Renaming a stage must not leave its old script and cache behind.
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    md = tmp_path / "README.md"
    md.write_text(
        "```python calkit stage name=old environment=main\nprint('x')\n```\n\n"
        "```text calkit output stage=old\nx\n```\n"
    )
    ck_info = {
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"}
            }
        }
    }
    expand_ck_info(ck_info)
    assert (tmp_path / ".calkit/markdown/README.md/old.py").is_file()
    assert (tmp_path / ".calkit/markdown/outputs/README.md/old.txt").is_file()
    md.write_text(
        "```python calkit stage name=new environment=main\nprint('x')\n```\n\n"
        "```text calkit output stage=new\nx\n```\n"
    )
    result = expand_ck_info(ck_info)
    assert not (tmp_path / ".calkit/markdown/README.md/old.py").exists()
    assert not (
        tmp_path / ".calkit/markdown/outputs/README.md/old.txt"
    ).exists()
    assert (tmp_path / ".calkit/markdown/README.md/new.py").is_file()
    assert sorted(result.removed_paths) == [
        ".calkit/markdown/README.md/old.py",
        ".calkit/markdown/outputs/README.md/old.txt",
    ]


def test_expand_ck_info_env_description_says_it_is_generated(
    tmp_path, monkeypatch
):
    # The notice lives in the environment, not a YAML comment.
    #
    # A comment is easy to delete without it ever coming back; a
    # description is data, and is rewritten on every compile.
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "<!-- calkit environment name=main -->\n- numpy\n\n"
        "```python calkit stage name=a\npass\n```\n"
    )
    ck_info = {
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"}
            }
        }
    }
    env = expand_ck_info(ck_info).environments["main"]
    assert env["description"] == (
        "Generated from README.md. Changes made here will be overwritten."
    )
    # An author's own description wins
    (tmp_path / "README.md").write_text(
        '<!-- calkit environment name=main description="Mine" -->\n'
        "- numpy\n\n"
        "```python calkit stage name=a\npass\n```\n"
    )
    assert expand_ck_info(ck_info).environments["main"]["description"] == (
        "Mine"
    )


def test_expand_ck_info_description_alone_is_not_a_conflict(
    tmp_path, monkeypatch
):
    # A differing description must not read as a competing definition.
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "<!-- calkit environment name=main -->\n- numpy\n\n"
        "```python calkit stage name=a\npass\n```\n"
    )
    ck_info = {
        "environments": {
            "main": {
                "kind": "uv",
                "path": ".calkit/envs/main/pyproject.toml",
                "description": "something a user typed",
            }
        },
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"}
            }
        },
    }
    assert expand_ck_info(ck_info).environments["main"]["kind"] == "uv"


def test_parse_markdown_file_cache_sees_edits(tmp_path):
    # The parse cache must never hide a change to the file.
    #
    # Project info is expanded several times over one status, so the cache
    # matters---but a stale one would silently run the previous version of
    # the code.
    import time

    from calkit.markdown import parse_markdown_file

    md = tmp_path / "README.md"
    md.write_text("```python calkit stage name=first\nprint(1)\n```\n")
    blocks = parse_markdown_file(str(md))
    assert [b.name for b in blocks] == ["first"]
    # Reading again is served from the cache, so it must be equivalent
    assert [b.name for b in parse_markdown_file(str(md))] == ["first"]
    # An edit is picked up. Sleep past the filesystem's timestamp
    # granularity so this tests the invalidation rather than the clock.
    time.sleep(0.01)
    md.write_text("```python calkit stage name=second\nprint(2)\n```\n")
    assert [b.name for b in parse_markdown_file(str(md))] == ["second"]
    # Including an edit that keeps the file exactly the same size
    time.sleep(0.01)
    md.write_text("```python calkit stage name=SECOND\nprint(2)\n```\n")
    assert [b.name for b in parse_markdown_file(str(md))] == ["SECOND"]


def test_parse_install_block_reads_shell_installers():
    from calkit.markdown import parse_install_block

    spec = parse_install_block("pip install numpy pandas", "sh")
    assert spec is not None
    assert spec.kind == "uv-venv"
    assert spec.packages == ["numpy", "pandas"]
    assert not spec.dev
    # The installer, not the language, says which kind of environment
    assert parse_install_block("uv add matplotlib", "bash").kind == "uv"
    assert parse_install_block("conda install -c conda-forge numpy", "sh") == (
        parse_install_block("conda install numpy", "sh")
    )
    # A channel is not a package
    assert parse_install_block(
        "conda install -c conda-forge numpy", "sh"
    ).packages == ["numpy"]
    # A spec file the command names is carried through
    assert (
        parse_install_block("pip install -r requirements.txt", "sh").spec_path
        == "requirements.txt"
    )
    # Installing the working directory is a dev install
    assert parse_install_block("pip install -e .", "sh").dev
    assert parse_install_block("uv sync", "sh").dev
    # Anything that isn't an install leaves the block alone
    assert parse_install_block("git clone https://example.com/x", "sh") is None
    assert parse_install_block("pip install numpy\nmake all", "sh") is None


def test_parse_install_block_reads_julia_and_r():
    from calkit.markdown import parse_install_block

    spec = parse_install_block('using Pkg\nPkg.add("Plots")', "julia")
    assert spec.kind == "julia"
    assert spec.packages == ["Plots"]
    assert parse_install_block(
        'using Pkg; Pkg.add(["DataFrames", "CSV"])', "julia"
    ).packages == ["DataFrames", "CSV"]
    assert parse_install_block('Pkg.develop(path=".")', "julia").dev
    # Package-mode and prompted transcripts read the same as plain calls
    assert parse_install_block("] add Plots", "julia").packages == ["Plots"]
    assert parse_install_block(
        'julia> using Pkg\n\njulia> Pkg.add("Oceananigans")', "julia"
    ).packages == ["Oceananigans"]
    # A block that also does work is code, not a declaration
    assert parse_install_block('Pkg.add("Plots")\nplot(1:10)', "julia") is None
    spec = parse_install_block('install.packages(c("ggplot2", "dplyr"))', "r")
    assert spec.kind == "renv"
    assert spec.packages == ["ggplot2", "dplyr"]
    # A remote is named owner/repo; the package is the repo
    assert parse_install_block(
        'remotes::install_github("tidyverse/dplyr")', "r"
    ).packages == ["dplyr"]
    assert parse_install_block("renv::restore()", "r").dev
    assert parse_install_block("library(ggplot2)\nggplot()", "r") is None


def test_annotate_code_blocks():
    from calkit.markdown import annotate_code_blocks

    text = (
        "# Demo\n\n"
        "Install it:\n\n"
        "```sh\npip install numpy\n```\n\n"
        "Then run it:\n\n"
        "```python\nimport numpy as np\n\nprint(np.pi)\n```\n\n"
        "Check it worked:\n\n"
        "```sh\ncalkit run README.md\n```\n"
    )
    new, annotated = annotate_code_blocks(text, "README.md")
    assert annotated.stages == {"py": "python"}
    assert annotated.environments == {"readme": "python"}
    assert "```sh calkit environment name=readme python=" in new
    assert "```python calkit stage name=py environment=readme\n" in new
    # A shell block that installs nothing is an instruction for a reader,
    # not a stage
    assert "```sh\ncalkit run README.md\n```" in new
    # Only info strings change
    assert [
        line for line in new.splitlines() if not line.startswith("```")
    ] == [line for line in text.splitlines() if not line.startswith("```")]


def test_annotate_code_blocks_joins_blocks_and_skips_transcripts():
    from calkit.markdown import annotate_code_blocks

    text = (
        "```python\nx = 1\n```\n\n"
        "```python\nprint(x)\n```\n\n"
        "```python\n>>> print(x)\n1\n```\n"
    )
    new, annotated = annotate_code_blocks(text, "README.md")
    # Blocks of a language join into one stage, in document order
    assert annotated.stages == {"py": "python"}
    assert new.count("```python calkit stage name=py\n") == 2
    # A transcript can't be run as it stands, so it is left alone
    assert "```python\n>>> print(x)" in new


def test_annotate_code_blocks_is_a_no_op_without_runnable_code():
    from calkit.markdown import annotate_code_blocks

    text = "# Docs\n\n```sh\nmake all\n```\n\n```text\nhello\n```\n"
    new, annotated = annotate_code_blocks(text, "README.md")
    assert not annotated
    assert new == text


def test_resolve_environments_dev_install_uses_the_project_spec(
    tmp_path, monkeypatch
):
    from calkit.markdown import (
        extract_environments,
        extract_stages,
        resolve_environments,
    )

    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    text = (
        "```sh calkit environment name=dev\npip install -e .\n```\n\n"
        "```python calkit stage name=py environment=dev\nprint(1)\n```\n"
    )
    blocks = parse_markdown(text, path="README.md")
    envs = resolve_environments(
        extract_environments(blocks, "README.md"),
        extract_stages(blocks, "README.md"),
        "README.md",
    )
    # pip was named, but the project describes itself with a pyproject, so
    # that is the environment---and there is nothing to generate
    assert envs["dev"]["kind"] == "uv"
    assert envs["dev"]["path"] == "pyproject.toml"
    assert envs["dev"]["_spec_content"] is None
    assert "will be overwritten" not in envs["dev"]["description"]


def test_extract_environments_merges_install_blocks():
    from calkit.markdown import extract_environments

    text = (
        "```sh calkit environment name=py\nuv add numpy\n```\n\n"
        "```sh calkit environment name=py\nuv add pandas\n```\n\n"
        # The same package fetched two ways is one dependency
        "```sh calkit environment name=py\nuv add numpy\n```\n"
    )
    envs = extract_environments(parse_markdown(text), "README.md")
    assert envs["py"]["_install"].packages == ["numpy", "pandas"]


def test_extract_environments_still_rejects_duplicate_lists():
    from calkit.markdown import extract_environments

    with pytest.raises(MarkdownParseError, match="more than once"):
        extract_environments(
            parse_markdown(
                "<!-- calkit environment name=a -->\n- numpy\n\n"
                "<!-- calkit environment name=a -->\n- scipy\n"
            ),
            "README.md",
        )


def test_installing_the_projects_own_package_is_a_dev_install(
    tmp_path, monkeypatch
):
    from calkit.markdown import (
        extract_environments,
        extract_stages,
        installs_local_package,
        local_package_source_paths,
        parse_install_block,
        resolve_environments,
    )

    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "wave-tools"\nversion = "0.1.0"\n'
    )
    (tmp_path / "src" / "wave_tools").mkdir(parents=True)
    (tmp_path / "src" / "wave_tools" / "__init__.py").write_text("")
    # A README tells a reader to install the package from wherever it is
    # published; inside its own repo that is the working tree
    assert installs_local_package(
        parse_install_block("uv add wave-tools", "sh")
    )
    assert installs_local_package(
        parse_install_block(
            "uv add git+ssh://git@github.com/me/wave-tools.git", "sh"
        )
    )
    assert not installs_local_package(
        parse_install_block("uv add numpy", "sh")
    )
    # The source is a dependency in its own right, because an editable
    # install is a pointer to the working tree
    assert local_package_source_paths("python") == ["src/wave_tools"]
    text = (
        "```sh calkit environment name=py\nuv add wave-tools\n```\n\n"
        "```python calkit stage name=py environment=py\nprint(1)\n```\n"
    )
    blocks = parse_markdown(text, path="README.md")
    envs = resolve_environments(
        extract_environments(blocks, "README.md"),
        extract_stages(blocks, "README.md"),
        "README.md",
    )
    assert envs["py"]["path"] == "pyproject.toml"
    assert envs["py"]["_spec_content"] is None


def test_parse_markdown_skips_commented_out_content():
    from calkit.markdown import MarkdownParseError, parse_markdown

    # Whatever an ordinary comment contains is commented out, fences
    # included, so a block inside one is not a stage
    text = (
        "<!--\n"
        "```python calkit stage name=hidden\nprint(1)\n```\n"
        "-->\n"
        "<!-- one line ```python calkit stage name=hidden2 -->\n"
        "```python calkit stage name=real\nprint(2)\n```\n"
    )
    assert [b.name for b in parse_markdown(text)] == ["real"]
    # A directive comment still attaches to the block below it
    text = (
        "<!-- not ours -->\n\n"
        "<!-- calkit stage name=a -->\n\n```python\npass\n```\n"
    )
    assert [b.name for b in parse_markdown(text)] == ["a"]
    # An unterminated comment is just Markdown with a typo
    text = "<!-- oops\n\n```python calkit stage name=a\npass\n```\n"
    assert [b.name for b in parse_markdown(text)] == ["a"]
    # Names become path components, so they have to be a single safe
    # segment rather than something that escapes the project
    for bad in ["../../tmp/payload", "a/b", ".hidden", "a b", "-x"]:
        with pytest.raises(MarkdownParseError, match="is not valid"):
            parse_and_extract = parse_markdown(
                f'```python calkit stage name="{bad}"\npass\n```\n'
            )
            from calkit.markdown import extract_stages

            extract_stages(parse_and_extract, "README.md")
        with pytest.raises(MarkdownParseError, match="is not valid"):
            from calkit.markdown import extract_environments

            extract_environments(
                parse_markdown(
                    f'<!-- calkit environment name="{bad}" -->\n- numpy\n'
                ),
                "README.md",
            )


def test_set_stage_attrs_directive_comment():
    from calkit.markdown import extract_stages, parse_markdown, set_stage_attrs

    # A stage declared in a comment gets the attribute written into the
    # comment, since there is no annotation on the fence to carry it
    text = "<!-- calkit stage name=a -->\n\n```python\npass\n```\n"
    new, changed = set_stage_attrs(text, "a", {"environment": "py"})
    assert changed
    assert new == (
        "<!-- calkit stage name=a environment=py -->\n\n```python\npass\n```\n"
    )
    specs = extract_stages(parse_markdown(new), "README.md")
    assert specs["a"].attrs == {"environment": "py"}
    # A multi-line comment is closed on its last line
    text = (
        "<!-- calkit stage name=a\n     inputs=[x.csv] -->\n\n"
        "```python\npass\n```\n"
    )
    new, changed = set_stage_attrs(text, "a", {"environment": "py"})
    assert changed
    assert new.splitlines()[1] == "     inputs=[x.csv] environment=py -->"
    # The author's word beats the detected one
    assert set_stage_attrs(new, "a", {"environment": "other"}) == (new, False)
    # A stage the file doesn't declare can't be written to
    assert set_stage_attrs(text, "nope", {"environment": "py"}) == (
        text,
        False,
    )


def test_set_output_blocks_lengthens_fence_for_output_containing_one():
    from calkit.markdown import (
        extract_outputs,
        parse_markdown,
        set_output_blocks,
    )

    # Output can contain a line that would close the block, which would
    # otherwise leave the rest of it rendering as Markdown
    text = "```text calkit output stage=a\nold\n```\n\nAfter.\n"
    new, changed = set_output_blocks(text, {"a": "line\n```\nmore"})
    assert changed
    assert new == (
        "````text calkit output stage=a\nline\n```\nmore\n````\n\nAfter.\n"
    )
    assert extract_outputs(parse_markdown(new), "README.md") == {
        "a": "line\n```\nmore"
    }
    # ...however long the run gets, and a fence that is already long
    # enough is left alone
    new2, _ = set_output_blocks(new, {"a": "````"})
    assert new2.startswith("`````text calkit output stage=a\n````\n`````\n")
    new3, _ = set_output_blocks(new2, {"a": "x"})
    assert new3.startswith("`````text calkit output stage=a\nx\n`````\n")
    # A run of the other fence character is just content
    new4, _ = set_output_blocks(text, {"a": "~~~"})
    assert new4.startswith("```text calkit output stage=a\n~~~\n```\n")


def test_expand_ck_info_file_level_fields(tmp_path, monkeypatch):
    from copy import deepcopy

    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(
        "```python calkit stage name=a inputs=[b.csv]\npass\n```\n\n"
        "```text calkit output stage=a\nhi\n```\n"
    )
    ck_info = {
        "pipeline": {
            "stages": {
                "guide": {
                    "kind": "markdown",
                    "target_path": "docs/guide.md",
                    "environment": "main",
                    "inputs": ["data.csv"],
                    "always_run": True,
                    "frozen": True,
                }
            }
        }
    }
    result = expand_ck_info(ck_info)
    assert result.markdown_paths == ["docs/guide.md"]
    stage = result.ck_info["pipeline"]["stages"]["guide/a"]
    # What the file declares for itself applies to every stage in it,
    # alongside what each block declares for itself
    assert stage["inputs"] == [
        "data.csv",
        "b.csv",
        ".calkit/markdown/outputs/docs/guide.md/a.txt",
    ]
    assert stage["always_run"] is True
    assert stage["frozen"] is True
    assert stage["environment"] == "main"
    # Outputs, iteration and a working directory belong to the blocks,
    # not the file, so setting them on the file is an error rather than
    # something quietly dropped
    for key, value in [
        ("outputs", ["x.txt"]),
        ("iterate_over", [{"arg_name": "n", "values": [1]}]),
        ("wdir", "docs"),
    ]:
        bad = deepcopy(ck_info)
        bad["pipeline"]["stages"]["guide"][key] = value
        with pytest.raises(ValueError, match="not defined properly"):
            expand_ck_info(bad)
    # The path is required, and must be a Markdown file
    for cfg in [
        {"kind": "markdown"},
        {"kind": "markdown", "target_path": "script.py"},
    ]:
        with pytest.raises(ValueError, match="not defined properly"):
            expand_ck_info({"pipeline": {"stages": {"x": cfg}}})


def test_expand_ck_info_env_declared_in_two_files(tmp_path, monkeypatch):
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "<!-- calkit environment name=main -->\n- numpy\n\n"
        "```python calkit stage name=a\npass\n```\n"
    )
    (tmp_path / "OTHER.md").write_text(
        "<!-- calkit environment name=main -->\n- pandas\n\n"
        "```python calkit stage name=b\npass\n```\n"
    )
    ck_info = {
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"},
                "OTHER.md": {"kind": "markdown", "target_path": "OTHER.md"},
            }
        }
    }
    # The entries look identical---the package lists live in the spec
    # files---so this has to be caught by ownership, not by comparison
    with pytest.raises(ValueError, match="declared in both"):
        expand_ck_info(ck_info)


def test_read_markdown_and_get_environments(tmp_path, monkeypatch):
    from calkit.markdown import get_environments, read_markdown

    monkeypatch.chdir(tmp_path)
    text = (
        "```sh calkit environment name=declared python=3.13\n"
        "pip install numpy\n```\n\n"
        "```python calkit stage name=a environment=declared\n"
        "import numpy\n```\n\n"
        "```python calkit stage name=b\nimport pandas\n```\n\n"
        "```text calkit output stage=b\nold\n```\n"
    )
    doc = read_markdown(text, "README.md")
    assert doc.path == "README.md"
    assert list(doc.stages) == ["a", "b"]
    assert doc.outputs == {"b": "old"}
    envs = get_environments(doc, existing_env_names=["readme"])
    assert list(envs.declared) == ["declared"]
    # Only the stage naming no environment gets one detected, named to
    # avoid both the project's environments and the file's own
    assert envs.assignments == {"b": "readme-2"}
    assert envs.detected["readme-2"]["kind"] == "uv"
    assert "pandas" in envs.detected["readme-2"]["_spec_content"]
    assert envs.detected_public == {
        "readme-2": {
            "kind": "uv",
            "path": ".calkit/envs/readme-2/pyproject.toml",
        }
    }
    # A default environment means nothing needs detecting
    envs = get_environments(doc, default_env="declared")
    assert envs.assignments == {} and envs.detected == {}


def test_values(tmp_path, monkeypatch):
    from calkit.markdown import (
        MarkdownParseError,
        extract_values,
        format_value,
        parse_markdown,
        set_values,
    )

    monkeypatch.chdir(tmp_path)
    (tmp_path / "results.json").write_text(
        '{"rms": 0.29330001, "n": 401, "fit": {"coeffs": [1.974, 0.1]}, '
        '"ok": true, "label": "damped"}'
    )
    (tmp_path / "other.json").write_text('{"n": 7}')
    text = (
        "# Title\n\n"
        "<!-- calkit values path=results.json -->\n\n"
        'The RMS is <!-- calkit value key=rms format="{:.4f}" -->?'
        "<!-- /calkit value --> over <!-- calkit value key=n -->"
        "<!-- /calkit value --> samples.\n\n"
        "| quantity | value |\n| --- | --- |\n"
        "| leading coefficient | <!-- calkit value key=fit.coeffs.0 -->"
        "stale<!-- /calkit value --> |\n\n"
        "Elsewhere: <!-- calkit value key=n path=other.json -->"
        "<!-- /calkit value -->, <!-- calkit value key=ok --><!-- /calkit value -->"
        ", <!-- calkit value key=label --><!-- /calkit value -->.\n\n"
        "````md\n"
        "<!-- calkit value key=rms -->example<!-- /calkit value -->\n"
        "````\n\n"
        "```python calkit stage name=a\npass\n```\n"
    )
    values = extract_values(text, "README.md")
    # Markers inside fenced code are examples, not values
    assert [(v.key, v.path, v.text, v.format, v.line) for v in values] == [
        ("rms", "results.json", "?", "{:.4f}", 5),
        ("n", "results.json", "", None, 5),
        ("fit.coeffs.0", "results.json", "stale", None, 9),
        ("n", "other.json", "", None, 11),
        ("ok", "results.json", "", None, 11),
        ("label", "results.json", "", None, 11),
    ]
    # The markers are invisible to the block parser
    assert [b.name for b in parse_markdown(text)] == ["a"]
    new, changed = set_values(text, "README.md")
    assert changed
    assert (
        'The RMS is <!-- calkit value key=rms format="{:.4f}" -->0.2933'
        "<!-- /calkit value --> over <!-- calkit value key=n -->401"
        "<!-- /calkit value --> samples."
    ) in new
    assert (
        "| leading coefficient | <!-- calkit value key=fit.coeffs.0 -->1.974"
        "<!-- /calkit value --> |"
    ) in new
    assert (
        "Elsewhere: <!-- calkit value key=n path=other.json -->7"
        "<!-- /calkit value -->, <!-- calkit value key=ok -->true"
        "<!-- /calkit value -->, <!-- calkit value key=label -->damped"
        "<!-- /calkit value -->."
    ) in new
    assert "<!-- calkit value key=rms -->example<!-- /calkit value -->" in new
    # Idempotent once in line with the results
    assert set_values(new, "README.md") == (new, False)
    # Without a format, numbers read exactly as the results file has them
    assert format_value(0.29330001) == "0.29330001"
    assert format_value(3) == "3"
    assert format_value(None) == "null"
    assert format_value(1234.5, "{value:,.1f}") == "1,234.5"
    # Errors name the line
    marker = "<!-- calkit value {} -->x<!-- /calkit value -->"
    for bad, match in [
        (marker.format(""), "must name a key"),
        (marker.format("key=rms"), "names no results file"),
        (marker.format("key=nope path=results.json"), "has no key 'nope'"),
        (marker.format("key=rms path=missing.json"), "does not exist"),
        (marker.format("key=rms path=results.json nope=1"), "unrecognized"),
        (
            marker.format('key=label path=results.json format="{:.2f}"'),
            "Could not format",
        ),
        ("<!-- calkit values path=results.json format=x -->", "only a 'path'"),
    ]:
        with pytest.raises(MarkdownParseError, match=match):
            set_values("Intro.\n\n" + bad + "\n", "README.md")
    # A value annotation on a fence is a mistake, not a block
    with pytest.raises(MarkdownParseError, match="inline marker"):
        parse_markdown("```python calkit value key=rms\npass\n```\n")


def test_expand_ck_info_one_stage_per_file(tmp_path, monkeypatch):
    from calkit.markdown import expand_ck_info

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "```python calkit stage name=a\npass\n```\n"
    )
    ck_info = {
        "pipeline": {
            "stages": {
                "README.md": {"kind": "markdown", "target_path": "README.md"},
                "again": {"kind": "markdown", "target_path": "README.md"},
            }
        }
    }
    # Two stages reading one file would fight over its derived files
    with pytest.raises(ValueError, match="another markdown stage already"):
        expand_ck_info(ck_info)
