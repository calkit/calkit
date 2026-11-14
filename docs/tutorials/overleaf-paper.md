# Making an Overleaf paper reproducible

<!--
First pass, written ahead of the features it describes; see the PR for
what's built. Screenshot placeholders name the file to drop into
img/overleaf-paper/.
-->

<!-- TODO: needs human review: the whole page, rewritten for the
laptop-first flow -->

Most papers on Overleaf are put together by hand. You run a notebook in
VS Code, it saves a figure, and when enough figures have changed, you drag
the whole figures folder into the Overleaf project. A diagram gets drawn in
Google Slides, downloaded, and uploaded. A number gets copied out of a
notebook's output and typed into the text. It works until the data or the
analysis changes, and then nobody is quite sure which figures are current,
which numbers came from which run, or how to make any of them again.

In this tutorial you'll keep your analysis on your laptop, in VS Code, and
keep writing on Overleaf, and connect the two. By the end, one command runs
whatever is out of date and puts the results in your paper, everything the
paper shows leads back to the notebook or script that made it, and a figure
on Overleaf opens the code behind it in VS Code. That loop is faster than
running notebooks and uploading by hand, which is the point: the faster it
is, the more often you go around it.

Unlike tools that put your code inside the paper, e.g., Quarto or
R Markdown, Calkit keeps the two separate but connected. When you're
writing, you're on Overleaf, and when you're analyzing, you're in your
notebooks, with only what that work needs in front of you. Calkit connects
them, so switching is cheap: a change to the analysis shows up in the
paper, and anything in the paper leads back to what made it.

You don't need to have used Calkit before, or Git, or Docker.

## What you need

- An [Overleaf](https://overleaf.com) account.
- A [GitHub](https://github.com) account, where the project's files are
  kept.
- An account on [calkit.io](https://calkit.io), which you can make with
  your GitHub account. It shows the project, its figures, and where they
  came from, so you can share it, and it's where you connect your GitHub,
  Overleaf, and Google accounts. Your analysis runs on your laptop.
- [VS Code](https://code.visualstudio.com) with the
  [Calkit extension](https://marketplace.visualstudio.com/items?itemName=calkit.calkit-vscode).
- The [Calkit browser extension](../browser-ext/index.md), signed in.
- A Google account, for the diagram drawn in Google Slides.
- Calkit, installed as below.
- For the last part, an AI agent with Calkit's skills, e.g.,
  [Claude Code](https://claude.com/claude-code) with the
  [Calkit plugin](../ai-tools.md#step-2-install-calkit-skills-globally).

To install Calkit, run this in a terminal on macOS or Linux:

```sh
curl -LsSf install.calkit.org | sh
```

or this in PowerShell on Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm install-ps1.calkit.org | iex"
```

This also lets the browser extension ask Calkit on your laptop to do
things, e.g., run a notebook, while you're on Overleaf. It talks to your
laptop directly, not through calkit.io.

## Get the starter files

The tutorial starts from a small paper and the analysis behind it, put
together the usual way, so you can try everything on something that isn't
your own work first. Download the two starter files:

- `starter-paper.zip`, the Overleaf project: a short paper about how fast a
  dye fades in solution at different temperatures.
- `starter-analysis.zip`, the analysis as it might be on your laptop: a
  folder of notebooks and a script, with a `figures` folder they save into,
  and next to it, the folder the spectrophotometer exported the
  measurements to.

On Overleaf, click **New Project**, then **Upload Project**, and pick
`starter-paper.zip`. Unzip `starter-analysis.zip` somewhere on your
computer and open the `dye-fading` folder in VS Code.

The analysis folder has:

- `fit_rates.ipynb`, which fits an exponential decay to the absorbance
  measured at each temperature, saves `figures/decay.png`, and prints the
  rate constants.
- `plot_spectra.py`, which plots the absorbance spectrum at the start of
  each run and saves `figures/spectra.png`.
- `arrhenius.ipynb`, which fits the rate constants against temperature to
  get the activation energy. Its rate constants are typed into a cell,
  copied from `fit_rates.ipynb`'s output, and it reads the temperature log
  from the spectrophotometer's folder, outside `dye-fading`.
- `figures`, with every figure as it was last saved.

There's no environment file, nothing records which notebook makes which
figure, and nothing says which order to run them in. The paper on Overleaf
has copies of the figures from the last time someone uploaded the folder,
a diagram of the setup downloaded from Google Slides, and the rate constant
at 25 °C typed into the text.

<!-- Screenshot: img/overleaf-paper/starter-paper.png
The starter paper on Overleaf, with the diagram, the plots, and typed
numbers. -->

## Make the folder a project

In VS Code, open a terminal in the `dye-fading` folder and run:

```sh
calkit new project . --hub
```

This makes the folder a Calkit project, with a copy of it on GitHub and a
page on calkit.io, without moving or changing your files.

Then bring the paper in, using its URL from your browser's address bar on
Overleaf:

```sh
calkit overleaf import https://www.overleaf.com/project/... paper
```

The paper is copied into a `paper` folder in the project and stays
connected to Overleaf: you keep writing there, and syncing brings changes
both ways.

Calkit sees that the paper's `figures/decay.png` and `figures/spectra.png`
are the same as the ones in your `figures` folder, and offers to keep them
in sync from there, so the paper always shows what the analysis last made.
Say yes.

If you already use Overleaf's Git integration, your clone of the Overleaf
project holds only the paper. Bring it in the same way, and work in the
project's `paper` folder from then on, so there's one copy.

## Record the first notebook

Run the first notebook through Calkit:

```sh
calkit xr fit_rates.ipynb
```

`xr` runs it and, since it worked, records it in the project's pipeline:
what it reads, what it saves, and an environment with the packages it
imports, so it runs the same way on any computer. Look in `calkit.yaml` to
see what it recorded.

The notebook printed the rate constants, and the paper has one typed in. A
printed number has nothing to point back to, so have the notebook save
them to a results file instead. Add a cell at the end:

```python
import json

with open("results/rates.json", "w") as f:
    json.dump(rates, f, indent=2)
```

Here `rates` maps each temperature to its rate constant, e.g.,
`{"25C": 0.0042, "35C": 0.0089}`. Then run everything that's out of date,
save the project, and sync the paper, all at once:

```sh
calkit run --save --overleaf
```

or click **Run, save, and sync** in VS Code's status bar.

On Overleaf, hover over the typed rate constant. Calkit finds the value in
`results/rates.json` that matches it, and offers to use it instead:

```latex
% Before
At 25 °C, the rate constant was 0.0042 s$^{-1}$.
% After
At 25 °C, the rate constant was \ckvalue[.4f]{results/rates.json}{25C}
s$^{-1}$.
```

`\ckvalue` comes from `calkit.sty`, which Calkit adds to your Overleaf
project along with a `\usepackage{calkit}` line in the preamble. It reads
the number from the results file every time the paper compiles, so it
can't be mistyped or left behind when the results change.

A number that isn't a result, e.g., one you're quoting from another paper,
can be left as is: add `% calkit: ignore` to the end of its line.

## Say where a figure came from, on Overleaf

You don't have to start from the terminal. Click the Calkit logo in
Overleaf's sidebar. Its **Components** list shows everything the paper
shows, with a dot for whether its origin is known, and in the editor and
on the PDF, anything with no recorded origin is marked in red.

<!-- Screenshot: img/overleaf-paper/components.png
The Calkit sidebar listing the figures and numbers, with the spectra plot
and the diagram marked red. -->

The spectra plot is still red. Hover over its `\includegraphics` line and
click **Define origin**, then pick `plot_spectra.py` from the list of your
project's scripts and notebooks. Calkit on your laptop does the rest: it
records the script the same way `xr` did, runs it, saves the project, and
syncs the paper, while the card on Overleaf shows how it's going.

<!-- Screenshot: img/overleaf-paper/define-origin-script.png
Defining the spectra plot's origin by picking plot_spectra.py. -->

## The diagram: drawn in Google Slides

The setup diagram was drawn on a slide in Google Slides. Instead of
downloading it again whenever it changes, have the pipeline export it.
Copy the slide's URL from your browser, with the slide selected, and run:

```sh
calkit new figure figures/setup.png --google-slide https://docs.google.com/presentation/d/...
```

The first time, Calkit asks you to connect your Google account. From then
on, whenever the pipeline runs, it checks whether the presentation has been
edited and, if so, exports the slide, cropped to what's drawn on it. You
keep drawing in Google Slides. See
[Google Workspace](../google-workspace.md) for more, e.g., putting the
project's plots into a slide.

## When xr isn't enough: hand it to an agent

Try the last notebook the same way:

```sh
calkit xr arrhenius.ipynb
```

This one stops. It reads the temperature log from outside the project, so
the pipeline couldn't run it anywhere else, and its rate constants are
typed in rather than read from what `fit_rates.ipynb` saves, so they'd go
stale. Fixing that takes judgment, which is a good job for an AI agent with
Calkit's skills. In VS Code, start your agent and ask it, e.g.:

> Add arrhenius.ipynb to the pipeline. It should read the rate constants
> from results/rates.json and the temperature log from the project, and
> save the activation energy in kJ/mol to a results file.

The agent copies the temperature log into the project, changes the notebook
to read the rate constants `fit_rates.ipynb` saves, records it in the
pipeline after `fit_rates.ipynb`, and runs it. Read what it changed before
you keep it: it's your analysis. Then, on Overleaf, right-click where the
activation energy goes, choose **Insert from Calkit**, and pick it.

## Change something and watch the paper follow

Now everything in the paper is accounted for, try changing it.

Say the decay plot's axis labels need units. On Overleaf, click the plot,
then **Open in VS Code** on its card. VS Code opens `fit_rates.ipynb`, the
notebook that makes it. Change the labels, then:

```sh
calkit run --save --overleaf
```

Calkit reruns only what's out of date, here the notebook and everything
downstream of it, and the new plot is on Overleaf a few seconds later. You
didn't export, upload, or retype anything, and you didn't have to remember
which notebook made which figure, or what had to run after it.

<!-- Screenshot: img/overleaf-paper/open-in-vscode.png
The decay plot's card on Overleaf, with the "Open in VS Code" button. -->

The same goes for the diagram: edit the slide in Google Slides, run, and
the new diagram is in the paper.

## Write the paper in VS Code too

You can keep writing on Overleaf, or write in VS Code, next to the
analysis. Open `paper/main.tex`, and the Calkit extension shows the PDF
beside it, with figures and numbers that lead back to what made them.
**Sync with Overleaf** in the Calkit sidebar brings your coauthors' changes
in and sends yours out.

Building the PDF on your laptop needs LaTeX, which Calkit installs for the
project the first time, without Docker.

## Start the paper at the start

The starter paper was put together after the analysis was done, which is
how most papers are. It works better the other way around: start the paper
as soon as you start the analysis, with a figure, a number, or a sentence
about what you expect, and fill it in as you go. Since running, saving, and
syncing is one step, the paper is always current, and you see your results
the way a reader will from the beginning.

## Release the paper for review

When nothing is left unaccounted for, you can release the paper for review.
Calkit checks that everything the paper shows can be traced all the way
back, builds the PDF, and gives you a link to share with reviewers. Figures
and numbers in the PDF link to where they came from, so a reviewer can see
the code and data behind any of them.

If anything is still unaccounted for, the release stops and says what, and
where it leads back to, e.g., a figure made from a data file nothing
records the source of.

<!-- Screenshot: img/overleaf-paper/release.png
Releasing the paper, and the shareable link. -->
