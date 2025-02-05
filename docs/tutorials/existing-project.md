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
e.g., if you have a "global" BibTeX file.
Locality helps keep things simple and reduce external dependencies.

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

## Put everything in version control

Now that we have everything in one project folder,
it's time to add files to version control.

## Add all computational processes to the pipeline

To be continued...

## Define all of the project artifacts
