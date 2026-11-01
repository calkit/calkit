# Making an Overleaf paper reproducible

<!--
First pass, written ahead of the features it describes; see the PR for
what's built. Screenshot placeholders name the file to drop into
img/overleaf-paper/.
-->

Most papers on Overleaf are put together by hand. Somebody runs a script,
saves a figure, and drags it into the Overleaf project. A diagram gets drawn
in PowerPoint, exported, and uploaded. A number gets copied out of a
notebook and typed into the text. It works until the data or the analysis
changes, and then nobody is quite sure which figures are current, which
numbers came from which run, or how to make any of them again.

In this tutorial you'll keep writing on Overleaf and drawing in PowerPoint,
exactly as you do now, and connect the paper to the analysis behind it.
By the end, everything the paper shows can be traced back to the code,
data, and files that made it, Overleaf tells you when something is out of
date, and one button brings it all up to date.

Unlike tools that put your code inside the paper, e.g., Quarto or
R Markdown, Calkit keeps the two separate but connected. When you're
writing, you're on Overleaf, and when you're analyzing, you're in your
scripts, with only what that work needs in front of you. Calkit connects
them, so switching is cheap: a change to the analysis shows up in the
paper, and anything in the paper leads back to what made it. The cheaper
the switch, the more often you can go around again.

You don't need to have used Calkit before, and you won't need a terminal.

## What you need

- An [Overleaf](https://overleaf.com) account.
- A [GitHub](https://github.com) account, where the project's files are
  kept.
- An account on [calkit.io](https://calkit.io), which you can make with
  your GitHub account.
- The [Calkit browser extension](../browser-ext/index.md), signed in.
- An Overleaf Git token, which lets Calkit read and update your Overleaf
  project. The extension asks for one the first time it needs it. See
  [Overleaf integration](../overleaf.md#generating-and-storing-an-overleaf-token)
  for how to make one.

## Get the starter paper

The tutorial starts from a small paper put together the usual way, so you
can try everything on something that isn't your own work first.
Download the two starter files:

- `starter-paper.zip`, the Overleaf project: a short paper about the drag
  on a cylinder towed through a tank.
- `starter-analysis.zip`, what's behind it, as it might be on your laptop:
  a script that plots the drag measurements, the measurements themselves,
  and the PowerPoint file the diagram of the setup was drawn in.

On Overleaf, click **New Project**, then **Upload Project**, and pick
`starter-paper.zip`. Unzip `starter-analysis.zip` somewhere on your
computer.

The paper shows three kinds of things, and each was made a different way:

- Figure 1, a diagram of the setup, drawn in PowerPoint, exported as a PNG,
  and uploaded.
- Figure 2, a plot of drag coefficient against Reynolds number, made by
  `plot_drag.py` and uploaded.
- Numbers in the text, e.g., the mean drag coefficient, which the script
  printed and someone typed in.

<!-- Screenshot: img/overleaf-paper/starter-paper.png
The starter paper on Overleaf, with the diagram, the plot, and typed
numbers. -->

## Connect the paper to a project

With the paper open on Overleaf, click the Calkit button in the bottom
right corner of the page. Since the paper isn't part of a project yet, the
panel offers to make it reproducible.

<!-- Screenshot: img/overleaf-paper/make-reproducible.png
The extension panel on an unconnected Overleaf paper, with the "Make this
paper reproducible" button. -->

Click **Make this paper reproducible** and give the project a name.
Calkit creates a project on calkit.io, with its files on GitHub, and brings
in a copy of your paper, which stays connected to Overleaf. You keep
writing on Overleaf, and changes go both ways when you sync.

## See what isn't accounted for

Click the Calkit logo in Overleaf's sidebar. Its **Components** list shows
everything the paper shows, with a dot for whether its origin is known.
In the editor and on the PDF, anything with no recorded origin is marked
in red, and numbers typed into the text are marked too.

<!-- Screenshot: img/overleaf-paper/components.png
The Calkit sidebar listing the figures and numbers, all marked red, with
the same marks in the editor and on the PDF. -->

At this point nothing is accounted for. Overleaf only ever saw the finished
files, so as far as anyone can tell, they could have come from anywhere.
Clicking an item jumps to it in the paper and shows what's known about it.

## Say where each thing came from

### The plot: made by a script

Hover over the plot's `\includegraphics` line, or click it in the sidebar,
and click **Define origin**. Choose **Script**, then upload `plot_drag.py`
and the measurements it reads, `drag_data.csv`.

<!-- Screenshot: img/overleaf-paper/define-origin-script.png
Defining the plot's origin by uploading the script and its data. -->

Calkit adds the script to the project and a step to the project's pipeline
that runs it in a Python environment and makes the plot. It also checks
that the script really writes the file the paper shows, and warns you if it
can't tell. The `\includegraphics` line becomes a `\ckfigure` naming where
the script saves the plot, so you don't have to rename or copy anything.

The measurements need an origin too, since a plot is only as traceable as
the data it was made from. You took them, so open the card's **Reads** list,
click **Define origin** on `drag_data.csv`, choose **Created**, and say who
took them.

### The diagram: exported from PowerPoint

Hover over the diagram and click **Define origin**. Choose **Exported**,
upload `setup.pptx`, and pick PowerPoint as the app it's drawn in.

Calkit adds the PowerPoint file to the project and a step that exports the
diagram from it whenever the pipeline runs, the same as a plot made by a
script. You keep drawing in PowerPoint. The only difference is what you
upload when the diagram changes: the PowerPoint file, instead of a PNG you
exported by hand.

### The numbers: saved by the script

The script printed the mean drag coefficient, and someone copied it into the
paper. A printed number has nothing to point back to, so the script needs to
save it to a results file instead.

On calkit.io, open `plot_drag.py` from the project's **All files** page,
click **Edit file**, and add two lines where the script prints the mean:

```python
import json

json.dump({"mean_cd": float(mean_cd)}, open("results/drag.json", "w"))
```

Then, back on Overleaf, click **Run and sync** on any red item. Calkit runs
the pipeline on GitHub Actions, which makes the plot, the diagram, and the
new results file, and syncs them to your paper when it's done. The sidebar
shows it running, then syncing.

Now hover over the typed mean drag coefficient. Calkit finds the value in
`results/drag.json` that matches it, and offers to use it instead:

```latex
% Before
The mean drag coefficient was 1.13.
% After
The mean drag coefficient was \ckvalue[.2f]{results/drag.json}{mean_cd}.
```

`\ckvalue` comes from `calkit.sty`, which Calkit adds to your Overleaf
project along with a `\usepackage{calkit}` line in the preamble. It reads
the number from the results file every time the paper compiles, so it
can't be mistyped or left behind when the results change.

A number that isn't a result, e.g., one you're quoting from another paper,
can be left as is: add `% calkit: ignore` to the end of its line.

## Make a change and bring everything up to date

Now everything in the paper is accounted for, try changing what's behind
it.

1. New measurements came in: on calkit.io, upload a new version of
   `drag_data.csv` with a few more rows.
2. The setup changed: open `setup.pptx` in PowerPoint, move the camera, and
   upload the new version from the diagram's card on Overleaf.

On Overleaf, the plot, the diagram, and the mean drag coefficient are all
marked out of date, since what they're made from has changed.
Click **Run and sync** once. The pipeline reruns only what's out of date,
and when it finishes, the paper has the new plot, the new diagram, and the
new mean, without you exporting, uploading, or retyping anything.

<!-- Screenshot: img/overleaf-paper/out-of-date.png
The plot, diagram, and number marked out of date, and the "Run and sync"
button on one of their cards. -->

## Add a second analysis

Papers grow. Say you now want to show how the wake behind the cylinder
recovers downstream, from a new script, `plot_wake.py`, that makes a figure
of velocity profiles and saves the velocity deficit at the last station.

On calkit.io, go to the project's **Pipeline** page and add a stage from
`plot_wake.py`, uploading the script and the data it reads. Calkit finds
what the script writes, i.e., the figure and the results file, and lists
them as the stage's outputs. Click **Run** to make them.

Back on Overleaf, put the cursor where the figure goes, right-click, and
choose **Insert from Calkit**. Pick the wake figure, and Calkit inserts a
`\ckfigure` for it and syncs it into the paper. Do the same in the text for
the velocity deficit, which inserts a `\ckvalue`.

<!-- Screenshot: img/overleaf-paper/insert-from-calkit.png
The "Insert from Calkit" picker listing the new figure and value. -->

Things you insert this way are accounted for from the start, so there's
nothing to define, and they stay current with **Run and sync** like
everything else.

## Do it with your own paper

The same steps work on a real paper. A few things come up there that the
starter doesn't have:

- **Code in a GitHub repository:** when defining a figure's origin, pick
  the repository and the script instead of uploading it. Calkit looks there
  for what the code needs to run, e.g., `requirements.txt`,
  `environment.yml`, or `pyproject.toml`.
- **Something downloaded:** choose **Imported** and give its URL, DOI, Git
  repository, or Calkit project. Calkit records it, and can check later
  whether the source has changed.
- **Data on Box or another shared drive:** bring it into the project on
  calkit.io rather than having scripts read it from the drive, so the
  pipeline can run anywhere.
- **Diagrams in other apps:** an Inkscape SVG or a GIMP file is exported
  automatically like a PowerPoint file. For anything else, say which app
  you export it with, and Calkit adds a manual step: nothing runs it for
  you, but the figure shows as out of date when its file changes, with a
  reminder of what to do, so nobody has to remember there was a step.
- **Working on the analysis:** click **Open in Codespaces** in the Calkit
  sidebar to work on the project in VS Code in your browser, with
  everything installed, or clone it to your computer with
  `calkit clone {owner}/{name}`.

You don't have to finish in one sitting. What's accounted for is saved
with the project, so you and your coauthors can pick it up where you left
off.

## Release the paper for review

When nothing is left unaccounted for, you can release the paper for review.
Calkit checks that everything the paper shows can be traced all the way
back, builds the PDF, and gives you a link to share with reviewers. Figures
and numbers in the PDF link to where they came from, so a reviewer can see
the script and data behind any of them.

If anything is still unaccounted for, the release stops and says what, and
where it leads back to, e.g., a figure made from a data file nothing
records the source of.

<!-- Screenshot: img/overleaf-paper/release.png
Releasing the paper, and the shareable link. -->
