# Converting an existing project to a Calkit project

!!! note

    This tutorial requires Calkit version 0.19.0 or above.
    If the output of `calkit --version` shows a lower version,
    run `pip install --upgrade calkit` or `calkit upgrade` to upgrade.

In this tutorial we're going to convert an existing project
into a Calkit project,
assuming we've never done anything like this before.
Thus, the project is not yet using any version control
or pipeline management system.
We're also going to do everything
in the most automated and hands-off way possible.
More flexibility can be achieved with the lower-level interfaces,
but for now, we just want to make the project reproducible as quickly
as possible with reasonable defaults.

Before we get started,
make sure that Calkit is installed,
you have an account on [calkit.io](https://calkit.io),
and have [set a token in your local config](../cloud-integration.md).

The basic steps we'll take here are:

1. Organize the project folder.
1. Create a new Calkit project.
1. Add all existing files to version control and back them up in the cloud.
1. Add all computational processes to the pipeline, ensuring they run in
   defined environments.
1. Define the project artifacts for presentation and consumption.

## Organize the project folder

The first step is to collect all of the files relevant to the project
and ensure they are in a single parent folder.
If you're a grad student, you might work on a single topic throughout
grad school, which means all of your research-related files can
go into a single project.
Note that we don't want to include things like coursework
or personal documents like your CV or transcripts.
The folder should only include materials relevant to planning,
performing, and publishing
the research.
Anything to be shared with the outside world,
and anything required to produce those things should be included.
If you have a script referencing some data outside this parent folder,
move the data inside and update the script accordingly.

Here's an example project folder layout:

```
📂 my-phd-research
├── 📂 data
│   ├── 📂 raw
│   └── 📂 processed
├── 📂 docs
│   └── 📜 notes.md
├── 📂 figures
│   ├── 📜 plot1.png
│   └── 📜 plot2.png
├── 📂 pubs
│   ├── 📂 proposal
│   │   ├── 📜 proposal.pdf
│   │   ├── 📜 proposal.tex
│   │   └── 📜 README.md
│   ├── 📂 2025-article-1
│   │   ├── 📜 paper.pdf
│   │   ├── 📜 paper.tex
│   │   └── 📜 README.md
│   ├── 📂 2025-aps-dfd-slides
│   │   ├── 📜 slides.pdf
│   │   └── 📜 slides.tex
│   ├── 📂 thesis
│   │   ├── 📂 chapters
│   │   ├── 📜 README.md
│   │   └── 📜 slides.pptx
├── 📂 scripts
│   ├── 📜 plot.py
│   └── 📜 process.py
├── 📂 simulations
│   ├── 📂 case1
│   │   ├── 📜 config.txt
│   │   └── 📜 output.h5
│   ├── 📂 case2
│   │   ├── 📜 config.txt
│   │   └── 📜 output.h5
│   └── 📜 run.py
└── 📜 references.bib
```

It's okay if the structure doesn't match exactly.
It's just important that everything is in there.
You can reorganize later.
We're mainly focused on minimizing external dependencies to
improve reproducibility.
That is,
the more self-contained we can make the project,
the easier it will be to reproduce,
since getting all of those external dependencies documented properly
and setup in a different context can be
a challenge.

It's a good idea to keep your library of references
(the BibTeX file `references.bib` in the example above)
in the project folder, rather than having any of your publications
reference a file outside the project,
e.g., if you have a "global" BibTeX file,
or a reference collection in an app like Zotero.

Similarly,
if you have files in cloud services like Dropbox or Overleaf,
download all of them to the project folder.
This project folder should be the single source of truth.
You can work on materials in other tools,
but if so,
the files should always be downloaded back to the main project folder.

!!! tip

    Don't be afraid to repeat yourself in code.
    There is a software engineering principle
    "don't repeat yourself," (DRY), which if applied too aggressively,
    can make it very difficult to track dependencies,
    which is crucial to maintaining reproducibility and simplicity.

    For example, imagine the `plot.py` and `process.py` script both contain
    similar logic for reading in raw data.
    One might be tempted to put this logic into a separate module so it's
    not written twice,
    but someday the requirement for plotting may change slightly,
    and if this module is a dependency for processing,
    technically the processing should be rerun to ensure reproducibility.
    If the processing is expensive, this could be wasteful.

    It's a good rule of thumb to wait until you've repeated a block of code
    three times before "abstracting" that logic into its own separate
    piece of code.
    That way, you can see how it's used and use the interface that emerged
    rather than attempting to design one from the start.

## Create/initialize the project

With a terminal open inside the project folder
(`my-phd-research` in the example above),
initialize it as a new Calkit project with:

```sh
calkit new project . \
    --name my-phd-research \
    --title "Experimental investigation of something" \
    --description "Investigating the effects of a thing." \
    --cloud
```

In this command, the `.` means the current working directory,
or "here."
The name, title, and description should be adapted to your own
project of course.
The name should be "kebab-case" (all lowercase with hyphens separating words),
the title should be sentence or title case,
and the description should include punctuation,
kind of like an abstract.

The `--cloud` flag is going to create a GitHub repo and Calkit Cloud project
for us, which will be linked together.
In the next step,
when we put the files in version control,
the code and text files will go to GitHub,
and the larger data files will go to the Calkit Cloud.
This will be handled seamlessly and transparently.

Note you can add a `--public` flag if you want the project to be public
from the get go.
This is encouraged but can be a little worrying at first.
The project can always be made public later,
so let's start with it private for now.

To summarize, this command will:

- Initialize a Git repository with GitHub as the remote
- Initialize a DVC configuration with the Calkit Cloud as the remote
- Create a `calkit.yaml` file for the project metadata
- Create a dev container specification in `.devcontainer` for use with VS Code
  or GitHub Codespaces
- Create a basic `README.md` file

## Put everything in version control

Now that we have everything in one project folder
and we have the project created in the cloud,
it's time to add files to version control.
If you run `calkit status`,
you'll see an output like:

```sh
$ calkit status
---------------------------- Project -----------------------------
Project status not set. Use "calkit new status" to update.

--------------------------- Code (Git) ---------------------------
On branch main
Your branch is up to date with 'origin/main'.

Untracked files:
  (use "git add <file>..." to include in what will be committed)
        .DS_Store
        data/
        docs/
        figures/
        pubs/
        references.bib
        scripts/
        simulations/

nothing added to commit but untracked files present (use "git add" to track)

--------------------------- Data (DVC) ---------------------------
No changes.

------------------------- Pipeline (DVC) -------------------------
There are no data or pipelines tracked in this project yet.
See <https://dvc.org/doc/start> to get started!
```

We have a list of files and folders that are untracked,
meaning they are not in version control yet.
We could add these with either `git add` or `dvc add`,
or we can let Calkit decide which makes the most sense depending
on the file type and size.

If you're a Mac user, you'll notice the `.DS_Store` file,
which is not something we want to keep in version control.
We can ignore that file with `calkit ignore .DS_Store`.
When you run `calkit status` again, you'll notice that file is no longer
in the list of untracked files, which is exactly what we want.
You can use `calkit ignore` with any other files or folders you want to keep
out of version control, but keep in mind that when something is not in
version control,
it's not available to collaborators,
and won't be present
in another copy of the project repo elsewhere, e.g., on a different computer.

Now let's go through our untracked folders one by one and start adding them
to the repo.
We can start with by running `calkit add` on `data/raw`:

```sh
$ calkit add data/raw -M
Adding data/raw to DVC since it's greater than 1 MB
100% Adding...|█████████████████████████████████████████████████|1/1 [00:00, 58.23file/s]
[main ee7b35b] Add data/raw
 2 files changed, 7 insertions(+)
 create mode 100644 data/.gitignore
 create mode 100644 data/raw.dvc
```

In the output, Calkit explains why that folder was added to DVC.
Note that we also used the `-M` flag,
which will automatically generate a commit message for us.
If you'd like to specify your own message, use `-m` instead.
You can see a list of all commits with `git log`.

Repeat the `calkit status` and `calkit add` process with
each of the files and folders until there are no more untracked files.
Be careful adding folders with lots of other files and folders inside.
It's usually a good idea to add these more granularly instead of all at once.
The `pubs` directory in our example is one such case.
There are PDFs in there, which typically belong in DVC instead of Git,
and there may be LaTeX output logs and intermediate files,
which should typically be ignored.

```sh
$ calkit add pubs/2025-aps-dfd-slides/slides.tex -M

Adding pubs/2025-aps-dfd-slides/slides.tex to Git
[main d680687] Add pubs/2025-aps-dfd-slides/slides.tex
 1 file changed, 0 insertions(+), 0 deletions(-)
 create mode 100644 pubs/2025-aps-dfd-slides/slides.tex
```

```sh
$ calkit add pubs/2025-aps-dfd-slides/slides.pdf -M

Adding pubs/2025-aps-dfd-slides/slides.pdf to DVC per its extension
100% Adding...|█████████████████████████████████████████████████|1/1 [00:00, 99.20file/s]
[main 757042b] Add pubs/2025-aps-dfd-slides/slides.pdf
 2 files changed, 6 insertions(+)
 create mode 100644 pubs/2025-aps-dfd-slides/.gitignore
 create mode 100644 pubs/2025-aps-dfd-slides/slides.pdf.dvc
```

If you want to manually control whether a target is tracked with Git or DVC,
you can use the `--to=git` or `--to=dvc` option.
Also, if you make a mistake along the way you can use the `git revert`
command, after finding the offending commit with `git log`.

### Back up the project in the cloud

After all relevant files are added and committed to the repo,
we can push to both GitHub and the Calkit Cloud with `calkit push`:

```sh
$ calkit push
Pushing to Git remote
Enumerating objects: 41, done.
Counting objects: 100% (41/41), done.
Delta compression using up to 10 threads
Compressing objects: 100% (29/29), done.
Writing objects: 100% (37/37), 3.29 KiB | 3.29 MiB/s, done.
Total 37 (delta 11), reused 0 (delta 0), pack-reused 0
remote: Resolving deltas: 100% (11/11), completed with 1 local object.
To https://github.com/your-name/my-phd-research
   dc09efe..8f21641  main -> main
Pushing to DVC remote
Checking authentication for DVC remote: calkit
Collecting                                                    |57.0 [00:00, 2.73kentry/s]
Pushing
42 files pushed
```

## Add all computational processes to the pipeline

Now that we have all of our files in version control,
we need to ensure that our output artifacts like derived datasets,
figures, and publication PDFs are generated with
[the pipeline](../pipeline/index.md).
This will ensure that they stay up to date if any of their
input data or dependencies change.

But first,
before building the pipeline,
we need to define computational environments to use in the stages.
This is important for reproducibility since our results will be less
dependent on the unique state of our local machine.
Others looking to reproduce our work will only need to have the
environment management software installed,
and the specific applications or packages needed will be installed
and used automatically by Calkit.

### Create computational environments

This project uses Python scripts,
so we'll first want to define an environment in which these will run.
If we want to use Conda (and it's installed), we can call:

```sh
calkit new conda-env --name py pandas matplotlib
```

In the command above we're specifying two packages to exist in the environment,
`pandas` and `matplotlib`.
However, you may have many more than this.
You can add them to the command or add them to the resulting
environment definition file
(`environment.yml` by default for Conda environments) later.
If you prefer Python's built-in `venv` module to manage your environment,
you can replace `conda-env` with `venv`,
and similarly, if you prefer `uv`, you can replace it with `uv-venv`.

After an environment is created,
it will be stored in the `environments` section of the `calkit.yaml` file.
It can also be modified (or removed) by editing that file.

If you have multiple Python scripts that require different,
possibly conflicting sets of packages,
you can simply create multiple environments and name them descriptively.
For example, instead of one environment called `py`,
you can create one called `processing` and one called `plotting`.

If you aren't using Python,
you can create other types of environments.
The main goal is to ensure that all processes are run in one if possible.
See the [environments documentation](../environments.md) for more information.

The project also compiles some LaTeX documents.
We can create a Docker environment called `tex` for these with:

```sh
calkit new docker-env --name tex --image texlive/texlive:latest-full
```

This environment is referencing a TeXLive Docker image from Docker Hub,
which requires [Docker](https://docker.com) to be installed,
but will not require a separate LaTeX distribution to be installed.
If you don't need the full TeXLive distribution, you can
select any other image you'd like from
[this list](https://hub.docker.com/r/texlive/texlive/tags).

### Add pipeline stages

Now we can create a stage for all of our important outputs.
For each of these, we'll define
what kind of stage it is,
the target file (script or LaTeX input),
which environment it should run in,
and any additional input dependencies or outputs.
Let's start with data processing:

```sh
calkit new stage \
    --name process-data \
    --environment py \
    --kind python-script \
    --target scripts/process.py \
    --dep data/raw \
    --out data/processed
```

This will add a stage to the `dvc.yaml` file that looks like:

```yaml
stages:
  process-data:
    cmd: calkit xenv -n py -- python scripts/process.py
    deps:
      - data/raw
      - environment.yml
      - scripts/process.py
    outs:
      - data/processed
```

This stage can also be modified later, e.g.,
if there end up being additional dependencies
(files or folders which if changed, require the script to be rerun).
See the
[DVC documentation](https://dvc.org/doc/user-guide/pipelines/defining-pipelines#stages)
for more information about defining pipeline stages.

Next, create a stage for plotting:

```sh
calkit new stage \
    --name plot \
    --environment py \
    --kind python-script \
    --target scripts/plot.py \
    --dep data/processed \
    --dep data/raw \
    --out figures
```

Then add stages to build our LaTeX documents:

```sh
calkit new stage \
    --name build-aps-slides \
    --environment tex \
    --kind latex \
    --target pubs/2025-aps-dfd-slides/slides.tex \
    --dep figures
```

```sh
calkit new stage \
    --name build-article-1 \
    --environment tex \
    --kind latex \
    --target pubs/2025-article-1/paper.tex \
    --dep figures
```

If you have other kinds of stages, e.g., MATLAB, R, or shell scripts to run,
see the output of `calkit new stage --help` for information on how to
create those.

### Check that the pipeline runs and push outputs to the cloud

Now that the pipeline is built,
we can check that it runs properly by calling:

```sh
calkit run
```

If there are no errors,
we can commit the outputs and push them up to the cloud with `calkit save`:

```sh
calkit save -am "Run pipeline"
```

## Declare all of the project artifacts

Project artifacts like datasets, figures, and publications
are declared in the [`calkit.yaml` file](../calkit-yaml.md).
The purpose of doing this is to make them more easily searchable and reusable.
For example,
users can run `calkit import dataset` in their own project to reuse
one of yours,
and your project will be listed as the source in that project's
`calkit.yaml` file.
See the [FAIR principles](https://www.go-fair.org/fair-principles/)
to learn more about why this is important.

Note that when they are ready for public consumption,
we can create a "release" that will archive these materials
to a service like
Figshare, Zenodo, or OSF, and give them a
digital object identifier (DOI) for citation and traceability.
It's a good idea to create a release of the project before submitting
a journal article and to cite it therein,
so readers can find their way back to the project and inspect how
the materials were created.

Let's go ahead an add our raw and processed datasets to `calkit.yaml`:

```yaml
datasets:
  - path: data/raw
    title: Raw data
  - path: data/processed
    title: Processed data
```

We can add more metadata about each dataset, e.g., a description,
or definitions for the columns,
but at the very least we need to define a path and title.

Next, add the figures to `calkit.yaml`.
This will make them show up in the figures section of the project homepage
on [calkit.io](https://calkit.io).

```yaml
figures:
  - path: figures/plot1.png
    title: Plot of something
    description: This is a plot of something.
    stage: plot
  - path: figures/plot2.png
    title: Plot of something else
    description: This is a plot of something else.
    stage: plot
```

You'll notice we've defined the pipeline stage that produced each of
these figures.
This will allow users to trace back from the figure to the code that
produced it.

Lastly, let's add our publications to `calkit.yaml`,
which will make them viewable on the project publications page on
calkit.io:

```yaml
publications:
  - path: pubs/2025-aps-dfd-slides/slides.pdf
    kind: presentation
    title: This is the title of the talk
    stage: build-aps-slides
  - path: pubs/2025-article-1/paper.pdf
    kind: journal-article
    title: This is the title of the paper
    stage: build-article-1
  - path: pubs/thesis/thesis.pdf
    kind: phd-thesis
    title: This is the title of the thesis
    stage: build-thesis
```

We can then commit and push the changes to `calkit.yaml` with:

```sh
calkit save calkit.yaml -m "Add artifacts to calkit.yaml"
```

## Next steps

Now that our project is fully version-controlled and reproducible,
we have a solid baseline to return to if anything breaks
due to future changes.
Maybe we have some new figures to generate,
or maybe we have a new idea for a derived dataset we can create.
A good way to go about doing this is to create a scratch script or notebook,
ignoring it with `calkit ignore`,
prototyping in that scratch space,
and moving any valuable code out into a version-controlled script once it
works the way you want it to.

After producing a new working script,
add a new pipeline stage to run that script with `calkit new stage`.
If you need a different environment, you can create one,
or you can update an existing environment by editing its definition file.
If you execute `calkit run` again, only the stages that are missing outputs
or have updated dependencies will be executed,
ensuring the project remains reproducible as efficiently as possible.
If you continue to commit all changes along the way,
you'll always be able to get back to something that works
if something goes wrong,
sort of like climbing with a safety harness,
clipping it onto higher and higher anchors as you ascend.

## Questions or comments?

Participate in the discussion
[here](https://github.com/orgs/calkit/discussions/241).
