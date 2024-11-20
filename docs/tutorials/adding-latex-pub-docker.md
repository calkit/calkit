# Adding a new LaTeX-based publication with its own Docker build environment

Have you ever wanted to collaborate with a team on a LaTeX article,
but have ran into roadblocks getting everyone on the team to install the
correct dependencies?
This can be especially difficult if different team members are using different
operating systems.
However, this is a perfect use case for building the paper with a Docker
container.
Here's how to do that by creating a publication in your project
and specifying a LaTeX template and Docker environment in which to build it,
all with one command:

```sh
calkit new publication \
    --title "This is the title" \
    --description "This is the description of the paper." \
    --kind journal-article \
    --template latex/article \
    --environment latex \
    --stage build-paper \
    ./paper
```

What happens when we do this:

1. A new publication is added to `calkit.yaml`.
1. A new Docker environment called `latex` is added to `calkit.yaml`.
   This environment uses an `_include` key so the details can be written to
   a different file, `.calkit/environments/latex.yaml`.
   This will allow us to use that environment specification as an input
   dependency for a DVC pipeline stage,
   such that if our environment changes, that stage will be rerun.
1. Files from a LaTeX template called "article" are copied into the `./paper`
   directory.
1. A new stage called `build-paper` is added to the DVC pipeline in `dvc.yaml`.
   It will have dependencies based on source files in `./paper`
   and an output based on the template's target file.
   Note that you can add more dependencies to the resulting pipeline stage
   with the `--dep` and `--deps-from-stage-outs` commands.
1. A Git commit is made automatically to add all of these files to the repo.
   Note this can be disabled with the `--no-commit` option.

If you need to add more dependencies to the stage later,
e.g., if you have a `.bib` file for references,
or add more figures,
you can add these by editing `dvc.yaml` directly.
