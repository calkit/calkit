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

1. Create a new Calkit project.
2. Add all existing files to version control and back them up in the cloud.
3. Add all computational processes to the pipeline, ensuring they run in
   defined environments.
4. Define the project artifacts for presentation and consumption.

## Create/initialize the project

Let's assume our project lives under our home directory,
e.g., `/home/{your name}/research/my-phd-work`.
The first thing we're going to do is open a terminal
in that directory.
We can open a terminal first and `cd` in there,
or on some systems we can right click on a folder in a file explorer
and there will be a shortcut to open a terminal there.
If you're using Windows, it's a good idea to use Git Bash for this rather
than the Windows Command Prompt or PowerShell.

Let's run `ls` to see what this directory looks like:

```sh
$ ls
data					environment.yml
```

ChatGPT thinks a typical grad student's files might be organized like:

```
📂 GradSchool
├── 📂 Coursework
│   ├── 📂 Semester1
│   │   ├── 📂 Course1_Name
│   │   │   ├── 📜 Lecture_Notes.pdf
│   │   │   ├── 📜 Assignments/
│   │   │   ├── 📜 Readings/
│   │   │   ├── 📜 Projects/
│   │   └── 📂 Course2_Name
│   ├── 📂 Semester2
│   └── ...
├── 📂 Research
│   ├── 📂 Papers
│   │   ├── 📜 Paper1.pdf
│   │   ├── 📜 Paper2.pdf
│   │   ├── 📜 Notes.md
│   ├── 📂 Data
│   │   ├── 📂 Raw
│   │   ├── 📂 Processed
│   │   ├── 📂 Results
│   ├── 📂 Code
│   │   ├── 📂 Experiments
│   │   ├── 📂 Scripts
│   │   ├── 📜 analysis.py
│   │   ├── 📜 README.md
│   ├── 📂 Thesis
│   │   ├── 📜 Chapters/
│   │   ├── 📜 Bibliography.bib
│   │   ├── 📜 Thesis_Draft.docx
│   │   ├── 📜 Figures/
│   ├── 📜 Research_Proposal.pdf
│   ├── 📜 Meeting_Notes/
├── 📂 Conferences
│   ├── 📜 Abstracts/
│   ├── 📜 Slides/
│   ├── 📜 Posters/
├── 📂 Admin
│   ├── 📜 CV.pdf
│   ├── 📜 Funding_Applications/
│   ├── 📜 Teaching/
│   ├── 📜 Travel_Reimbursements/
└── 📂 Misc
    ├── 📜 Useful_Readings/
    ├── 📜 Side_Projects/
    ├── 📜 TODO.md
```

This kind of layout is probably pretty typical.

For a grad student, they might work on a single topic throughout
grad school,
so let's reorganize the `Research` folder around a project-based layout.

Separating coursework, admin, and miscellaneous files from research
is a good idea,
but the way `Conferences` and `Research` are laid out
can be improved.

(Let's also move away from camelcase with underscores and use kebab-case)

We're going to shoot for a project-based structure like:

```
📂 grad-school
├── 📂 coursework
│   ├── 📂 semester1
│   └── ...
├── 📂 research
│   ├── 📂 paper-1
│   │   ├── 📜 paper.tex
│   │   ├── 📜 paper.pdf
│   │   ├── 📜 README.md
│   ├── 📂 data
│   │   ├── 📂 raw
│   │   ├── 📂 processed
│   ├── 📂 figures
│   │   ├── 📜 plot1.png
│   │   ├── 📜 plot2.png
│   ├── 📂 scripts
│   │   ├── 📜 plot.py
│   │   ├── 📜 process.py
│   ├── 📂 thesis
│   │   ├── 📂 chapters
│   │   ├── 📜 README.md
│   │   ├── 📜 slides.pptx
│   ├── 📜 README.md
├── 📂 conferences
│   └── 📂 2025-aps-dfd
│       └── 📜 registration.pdf
├── 📂 admin
│   ├── 📜 2024-transcript.pdf
│   └── ...
└── 📂 misc
    └── 📜 notes.md
```

Let's assume the entire `research` folder involves one research project
answering a set of related questions.
If this were not the case, we could create a subdirectory for each project
underneath.

Let's see what an ideal research project layout might look like:

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
│   └── 📂 case2
└── 📜 README.md
```

First, get your project organized similarly to the layout above.
Put everything in the single project folder.

What belongs in the project folder?
Basically anything related to collecting data,
processing data,
and publishing results.

Personal information like transcripts or coursework do not belong in
the research project materials.

So if we assume all of these files already exist,
but are potentially scattered about,
reorganize them into a single project folder.

It's okay if the structure doesn't match exactly.
It's just important that everything is included.
You can reorganize later.

If it doesn't look like this, e.g.,
maybe `data` and `thesis` don't live in the same folder,
reorganize your files so all materials relevant to the research
are in one folder.

## Put everything in version control

Now that we have everything in one project folder,
it's time to add files to version control.

## Add all computational processes to the pipeline

To be continued...
