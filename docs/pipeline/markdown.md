# Runnable Markdown

A Markdown file can declare pipeline stages and environments by annotating
its code blocks, so a README can be the source of truth for what it
documents.
Every annotated block is a real stage: it runs in a real environment, its
inputs and outputs are tracked, it is skipped when nothing it depends on has
changed, and what it prints can be written back into the file.
A README that drifts from the code becomes something Calkit can catch.

For a complete working project, see the
[runnable README example](https://github.com/calkit/calkit/tree/main/examples/markdown),
which you can create a copy of with:

```sh
calkit new project my-readme --template calkit/calkit/examples/markdown
```

## Declaring the stage

A `markdown` stage in `calkit.yaml` stands in for however many stages the
file declares:

```yaml
pipeline:
  stages:
    README.md:
      kind: markdown
      target_path: README.md
```

`target_path` is the Markdown file.
The stage name can be anything, though keying it by the path reads well.
When the pipeline is compiled, the stage is replaced by one stage per
annotated block name, called `<stage name>/<block name>`,
e.g., `README.md/analysis`.
Those are what `calkit run` and the rest of the tooling see.

The quickest way to get here from a plain README is `calkit xr`,
described [below](#bootstrapping-with-calkit-xr).

## Annotating code blocks

An annotation is written after the language in a fence's info string.
Markdown renderers take the first token as the language and ignore the
rest, so the block still highlights as usual on GitHub:

````md
```python calkit stage name=analysis environment=py outputs=[data/data.csv]
import numpy as np

np.savetxt("data/data.csv", np.linspace(0, 1, 10))
```
````

The annotation is `calkit stage` followed by `key=value` attributes.
Values are YAML, so anything a stage accepts in `calkit.yaml` can be
written inline, e.g., `outputs=[{path: fig.png, storage: git}]`.
A boolean can be written either way: `always_run=true`, or just
`always_run`, since a bare key with no `=` means `true`.

Names are used as path components (for the script extracted from the block),
so they may only contain letters, digits, `.`, `_`, and `-`.

### Supported languages

A block's language decides how it is run and which kind of stage it
becomes:

| Fence language      | Stage kind      |
| ------------------- | --------------- |
| `python`, `py`      | `python-script` |
| `r`                 | `r-script`      |
| `julia`, `jl`       | `julia-script`  |
| `sh`, `bash`, `zsh` | `shell-script`  |
| `matlab`, `octave`  | `matlab-script` |

Blocks with no annotation are inert, whatever their language,
which is what makes it safe to keep shell instructions for the reader
and deliberately wrong examples in the same file.

### One stage across several blocks

Blocks sharing a stage name are joined, in document order, into one script.
This is what lets an example be narrated across several code blocks:

````md
First, build the data:

```python calkit stage name=analysis environment=py
x = [1, 2, 3]
```

Then do something with it, still in the same stage:

```python calkit stage name=analysis outputs=[out.txt]
open("out.txt", "w").write(str(sum(x)))
```
````

Attributes can be spread across the blocks;
setting one to two different values is an error.
All blocks of a stage must share a language.

### Directive comments

When a declaration gets too long to sit comfortably on the fence,
it can go in an HTML comment directly above the block instead,
which is invisible when the file is rendered:

````md
<!-- calkit stage name=example environment=py
     inputs=[data/one.csv, data/two.csv]
     outputs=[out.png] -->

```python
print("hello")
```
````

The comment attaches to the block immediately below it
(blank lines in between are fine).
Attributes can be split between the comment and the fence,
but setting the same one in both places is an error.

### Documenting annotations without declaring them

A longer fence can contain shorter ones, so examples of annotated blocks
can be shown inside a fence of four backticks without becoming stages.
That is how this page, and the example project's README, are written.

## Environments

A README says what its code needs by showing how to install it,
so that is what Calkit reads.
Annotate the install block with `calkit environment`:

````md
```sh calkit environment name=py python=3.13
uv add numpy matplotlib
```
````

The installer says which kind of environment it is:

| Install command                                    | Environment kind |
| -------------------------------------------------- | ---------------- |
| `uv add`                                           | `uv`             |
| `pip install`, `uv pip install`                    | `uv-venv`        |
| `conda install`, `conda env create`, `mamba`, ...  | `conda`          |
| `Pkg.add(...)` or `pkg> add` (Julia)               | `julia`          |
| `install.packages(...)`, `remotes::install_github` | `renv`           |

Every statement in the block must be an install for it to count.
Calkit resolves and locks the environment exactly as it would one written
out in `calkit.yaml`: the spec is written to `.calkit/envs/<name>/`
(committed, along with its lock file), and the environment entry is
written into `calkit.yaml` with a description saying where it came from.
The Markdown stays authoritative; those entries are rewritten on every
compile, and removed if the Markdown stops declaring them.

An environment can also be declared as a list of packages under a
directive comment, for a file that would rather not show a command:

```md
<!-- calkit environment name=py python=3.13 -->

- numpy
- matplotlib
```

The kind is inferred from the language of the stages using the environment
(`uv` for Python, `julia`, `renv` for R), or set with `kind=`.
Julia environments need a version, e.g., `julia=1.12`.

### Which environment a stage uses

A stage names its environment with `environment=`.
A file declaring exactly one environment doesn't have to name it on every
block.
Otherwise, blocks naming none use the `environment` set on the `markdown`
stage in `calkit.yaml`, which defaults to `_system`.

### Projects that install themselves

A package's README usually says to install the package itself:

````md
```sh calkit environment name=dev
pip install -e .
```
````

Read inside the package's own repository, that means the working tree,
and the project already describes that environment in its
`pyproject.toml` (or `Project.toml`, or `DESCRIPTION`).
So rather than generating a second spec, the environment points at the
project's own, and every stage using it depends on the package's source,
so editing the library reruns the examples that use it.
`uv sync`, `uv add <this package>`, `Pkg.develop(path=".")`, and
`renv::restore()` all say the same thing in their own languages.

An install that names the project's package _alongside_ other packages,
e.g., `Pkg.add(["ThisPackage", "SomethingElse"])`, gets a generated
environment containing the other packages, with the project's own coming
from the working tree (as a path dependency) rather than a registry.
Either way, stages using the environment depend on the package's source,
so editing the library reruns the examples that use it.

## Output blocks

What a stage prints can be written back into the file,
so the README's claims about what the code prints are what it actually
printed:

````md
```text calkit output stage=analysis
fitted quadratic coefficient: 1.974
n points: 50
```
````

After each run, the block's body is replaced with the stage's standard
output.
The content is also cached as a dependency of the stage,
so editing the block by hand makes the stage stale rather than leaving the
file quietly claiming something untrue.

## File-level settings

`inputs`, `always_run`, `frozen`, and `scheduler` set on the `markdown`
stage in `calkit.yaml` apply to every stage the file declares
(a block's own `inputs` are added to the file's).
`outputs`, `iterate_over`, and `wdir` are not supported on the file as a
whole; declare them on the blocks.

## Values

Numbers in the prose can be kept current too, the way
[`json-to-latex`](index.md#json-to-latex) does for LaTeX.
A stage writes its results to a JSON file it declares as an output:

````md
```python calkit stage name=analysis environment=py outputs=[results.json]
json.dump({"rms": rms, "n": t.size}, open("results.json", "w"))
```
````

and the prose refers to values in it by key, between a pair of markers
that are invisible when rendered:

```md
The RMS is <!-- calkit value key=rms path=results.json format="{:.4f}" -->0.2933<!-- /calkit value -->
over <!-- calkit value key=n path=results.json -->401<!-- /calkit value --> samples.
```

After every run, the text between each pair is rewritten from the results
file, so the file says what was actually computed.
Keys can be dotted to reach into nested objects and lists, e.g.,
`fit.coeffs.0`.
`format` is a Python format string applied to the value,
e.g., `format="{:.2%}"` or `format="{value:,}"`;
without one, numbers read exactly as the results file has them.
A `calkit values path=results.json` directive sets the results file for
every marker after it, so a file drawing on one results file needn't name
it each time.
Markers inside fenced code are examples and are left alone.

## Running

Assuming you named your stage `README.md`, as `calkit xr` does,
name the stage or one of the stages it declares:

```sh
calkit run README.md
calkit run README.md/analysis
```

A stage keyed by some other name is run by that name, like any other
stage kind.

Stages depend on the scripts extracted from their blocks
(written under `.calkit/markdown/`, which is Git-ignored),
not on the Markdown file itself,
so editing prose never invalidates anything, and editing a code block
invalidates only the stage that block belongs to.

In VS Code, the Calkit extension puts a "Run stage" action above each
annotated block, and lists the file's stages under it in the sidebar.

## Bootstrapping with `calkit xr`

`calkit xr README.md` turns a plain README into a pipeline:

1. Code blocks in Python, R, or Julia are annotated as stages,
   named for their language (`py`, `r`, `jl`) so consecutive blocks join
   into one script per language, and blocks that install packages are
   annotated as the environment those stages run in.
   Blocks that already carry an annotation are left alone, and shell
   blocks are never promoted to stages, since those are usually
   instructions for the reader.
2. Stages that still name no environment get one detected from their
   imports, written to `.calkit/envs/`, and recorded on the block.
3. The project is initialized if it isn't one yet, the `markdown` stage is
   added to `calkit.yaml`, and the stages are run.
   If one fails, everything `xr` changed is put back.

Use `--dry-run` to see what would be annotated and created without
changing anything.
Nothing is committed by `xr`: initialization leaves its files staged, so
a failed run can put everything back.

### Checking a README without making a Calkit project

`calkit xr README.md --no-record` runs the file's stages and then
restores `calkit.yaml`, `dvc.yaml`, and `.dvc`, so the project doesn't
become a Calkit project. What the run produced stays for inspection: the
annotated fences, injected output and values, the stages' outputs, and
the extracted scripts and environments under `.calkit/`. This is the
mode for testing that a README is runnable in a repository that has no
interest in a pipeline. Nothing is ever committed.

A run that fails---in either mode, interrupts included---cleans up after
itself entirely: the record files, the Markdown file, and the derived
files it created are all put back, leaving only the run log under
`.calkit/local/logs/`.
