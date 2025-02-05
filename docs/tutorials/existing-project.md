# Converting an existing project to a Calkit project

In this tutorial we're going to convert an existing project
into a Calkit project.
We're going to assume this project is not using any version control system.
We're also going to do everything
in the most automated and hands-off way possible.
More flexibility can be achieved with the lower-level interfaces,
but for now, we just want to make the project reproducible as quickly
as possible with reasonable defaults.

Before we get started,
make sure that Calkit is installed,
you have an account on [calkit.io](https://calkit.io),
and have [set a token in your local config](../cloud-integration.md).

1. Organize the project folder.
1. Create a new Calkit project.
1. Add all existing files to version control and back them up in the cloud.
1. Add all computational processes to the pipeline, ensuring they run in
   defined environments.
1. Define the project artifacts for presentation and consumption.

## Organize the project folder

The first step is to collect up all of the files relevant to the project
and ensure they are in a single folder with nothing else in it.
If you're a grad student, you might work on a single topic throughout
grad school, which means all of your research-related files can
go into a single project.
Note that we don't want to include things like coursework
or personal things like your CV or transcripts.
The folder should only include materials relevant to planning,
performing, and publishing
the research.

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
├── 📜 references.bib
└── 📜 README.md
```

Anything to be shared with the outside world,
and anything required to produce those things should be included.
That is,
if you have a script referencing some data outside the folder,
move the data into the folder and update the script accordingly.
Make it all local.

It's okay if the structure doesn't match exactly.
It's just important that everything is in there.
You can reorganize later.

If it doesn't look like this, e.g.,
maybe `data` and `thesis` don't live in the same folder,
reorganize your files so all materials relevant to the research
are in one folder.

It's a good idea to keep your library of references
(the BibTeX file `references.bib` in the example above)
in the project folder, rather than having any of your publications
reference a file outside the project,
e.g., if you have a "global" BibTeX file,
or a reference collection in an app like Zotero.
Similarly,
if you have files in other cloud services like Overleaf,
download all of them to the project folder.
Locality helps keep things simple and reduce external dependencies.
This project folder should be the single source of truth.
You can potentially work on things in other tools,
though that may not be worth the complexity,
but if you do work on them externally,
the files should always be downloaded back to the main project folder.

!!! tip

    Don't be afraid to repeat yourself in code.
    There is a common software engineering principle
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
    three times before "abstracting" that logic into its own thing.
    That way, you can see how it's used and use the interface that emerged
    rather than attempting to design one from the start.

## Create/initialize the project

Inside the project folder, i.e., after calling `cd my-phd-research`,
create a new Calkit project inside with:

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
project.
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
from the get-go.
This is encouraged but can be a little worrying at first.
The project can always be made public later,
so let's start private for now.

The actions that Calkit will take are:

- Initialize a Git repository with GitHub as the remote
- Initialize a DVC configuration with the Calkit Cloud as the remote
- Create a `calkit.yaml` file for the project metadata
- Create a dev container specification in `.devcontainer` for use with VS Code
  or GitHub Codespaces
- If one doesn't exist already, a `README.md` file will be created

## Put everything in version control

Now that we have everything in one project folder,
it's time to add files to version control.

## Add all computational processes to the pipeline

### Create computational environments

This project uses Python scripts,
so we'll first want to define an environment in which these will run.
If we use Conda, we can call:

```sh
calkit new conda-env --name py pandas matplotlib
```

In the command above we're specifying two packages to exist in the environment,
`pandas` and `matplotlib`.
However, you may have many more than this.
You can add them to the command or add them to the resulting
environment definition file later.
If you prefer Python's built-in `venv` module to manage your environment,
you can replace `conda-env` with `venv`,
and similarly, if you prefer `uv`, you can replace it with `uv-venv`.

If you have multiple Python scripts that require different,
possibly conflicting sets of package,
you can simply create multiple environments and name them descriptively.
For example, instead of one environment called `py`,
you can create one called `processing` and one called `plotting`.

If you aren't using Python,
you can create other types of environments.
We just want to ensure that all of our processes are run in one,
rather than being purely dependent on the global machine environment.
See the [environments documentation](../environments.md) for more information.

The project also compiles some LaTeX documents.
We can create a Docker environment called `tex` for these with:

```sh
calkit new docker-env --name tex --image texlive/texlive:latest-full
```

If you don't need the full TeXLive distribution, you can
select any other image you'd like from
[this list on Docker Hub](https://hub.docker.com/r/texlive/texlive/tags).

### Add pipeline stages

```sh
calkit new stage \
    --name process-data \
    --environment py \
    --kind python-script \
    --target scripts/process.py \
    --dep data/raw \
    --out data/processed
```

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

## Run the pipeline and push outputs to the cloud

Lastly,
we can check that the pipeline runs properly by calling:

```sh
calkit run
```

If there are no errors,
we can commit the outputs and push them up to the cloud with:

```sh
calkit save -am "Run pipeline"
```

## Declare all of the project artifacts

If your project has produced any datasets that might be useful to others,
declare these in the `datasets` section.

Note that when they are ready for public consumption,
we can create a "release" that will archive these and give them a
digital object identifier (DOI) for citation and traceability.
It's a good idea to create a release of the project before submitting
a journal article and citing inside,
so readers can find their way back to the project and inspect how
things were created.

## Next steps

## Questions or comments?

Participate in the discussion
[here](https://github.com/orgs/calkit/discussions/241).
