# Making an Overleaf paper reproducible

<!--
First pass, written ahead of the features it describes; see the PR for
what's built. Screenshot placeholders name the file to drop into
img/overleaf-paper/.
-->

Most papers on Overleaf are put together by hand. Somebody runs a script,
saves a figure, and drags it into the Overleaf project. A number gets
copied out of a notebook and typed into the text. It works until the data
or the analysis changes, and then nobody is quite sure which figures are
current, which numbers came from which run, or how to make any of them
again.

In this tutorial you'll keep writing on Overleaf exactly as you do now, and
work through the paper one item at a time, pointing at each figure, table,
and number and saying where it came from. By the end, everything the paper
shows can be traced back to the code and data that made it, and Overleaf
tells you when something is out of date.

You don't need to have used Calkit before, and you don't need to change how
your analysis is organized to get started.

## What you need

- A paper on [Overleaf](https://overleaf.com).
- The [Calkit browser extension](../browser-ext/index.md), signed in.
- An account on [calkit.io](https://calkit.io).
- An Overleaf Git token, which lets Calkit read and update your Overleaf
  project. The extension asks for one the first time it needs it. See
  [Overleaf integration](../overleaf.md#generating-and-storing-an-overleaf-token)
  for how to make one.

Your analysis can be anywhere: in a repository on GitHub, in a folder on
your computer, or nowhere yet. You'll say which when you get to it.

## Connect the paper to a project

Open your paper on Overleaf and click the Calkit button in the bottom right
corner of the page. Since the paper isn't part of a project yet, the panel
offers to make it reproducible.

<!-- Screenshot: img/overleaf-paper/make-reproducible.png
The extension panel on an unconnected Overleaf paper, with the "Make this
paper reproducible" button. -->

Click **Make this paper reproducible** and give the project a name.
Calkit creates a project on calkit.io and brings in a copy of your paper,
which stays connected to Overleaf. You keep writing on Overleaf, and
changes go both ways when you sync.

## See what isn't accounted for

Once the paper is connected, the panel lists everything the paper shows
that nothing records the origin of yet:

- figures, from `\includegraphics`
- tables, from `\input`
- numbers typed into the text that look like results, e.g., an error, a
  speedup, or a p-value

<!-- Screenshot: img/overleaf-paper/checklist.png
The checklist in the extension panel, e.g., "3 of 12 accounted for", with
figures, tables, and numbers listed. -->

At this point it's normal for nothing to be accounted for. Overleaf only
ever saw the finished files, so as far as anyone can tell, they could have
come from anywhere. The rest of the tutorial works down this list.

Clicking an item jumps to it in the paper, and putting the cursor on an
item in the paper selects it in the list.

## Say where something came from

Pick an item, e.g., the first figure, and click **Where did this come
from?** There are five answers.

<!-- Screenshot: img/overleaf-paper/where-from.png
The five choices for one figure. -->

### Made by code in a GitHub repository

If the code that made the figure is in a repository on GitHub, choose the
repository, then the script or notebook that makes the figure. Calkit looks
in the repository for what the code needs to run, e.g., a
`requirements.txt`, `environment.yml`, or `pyproject.toml`, and asks you to
confirm it, or to pick one if there are several.

<!-- Screenshot: img/overleaf-paper/pick-script.png
Choosing the script and its environment from a connected repository. -->

From that, Calkit adds a step to the project's pipeline that runs the
script in that environment and produces the figure. The next time you need
the figure, you run the pipeline rather than remembering which script to
run, with which packages, in what order.

If the script reads data files, Calkit lists them, and each one goes on the
checklist too. A figure is only as traceable as the data it was made from.

### Made by code on your computer

If the code is in a folder on your computer and not in a repository, it
needs to go somewhere Calkit can see it. The panel shows a command to copy
into a terminal, which downloads the project you just made, paper and all:

```sh
calkit clone {your project URL}
```

Move your scripts, notebooks, and data into the new folder, then follow
[converting an existing project](existing-project.md#put-everything-in-version-control)
from where the files go into version control. When you come back to Overleaf,
the project's scripts show up to pick from, the same as a GitHub
repository's.

### Downloaded from somewhere

If the figure, table, or data came from somewhere else, e.g., another
paper, a data repository, or a colleague's project, give its URL or DOI.
Calkit records it, and can check it again later to see whether the source
has changed.

### Exported manually from a file you made

Plenty of figures aren't made by code: a diagram drawn in Illustrator or
Inkscape, a photo touched up in Photoshop, or a plot laid out in
PowerPoint.
What goes into the paper is a PNG or PDF exported from that file,
and that file is what you'd change if the figure had to.

Choose **Exported**, then pick or upload the file it's exported from.
Calkit records the file as yours.
If it's an Inkscape SVG or a GIMP file, Calkit exports the figure from it
whenever the pipeline runs, the same as a figure made by a script.
For anything else, say which app you export it with, and Calkit adds a
manual step to the pipeline.

Nothing runs a manual step for you, but Calkit keeps track of whether it's
been done.
Months later, when the reviews come back and you change the diagram, the
figure in the paper shows as out of date, with a reminder that it needs a
manual step.
Running the pipeline on your computer opens the file in its app, waits
while you export the figure, then checks the new export is there before
carrying on.
The figure in the paper can't quietly fall behind the file it came from,
and nobody has to remember there was a manual step at all.

### Drawn or measured by you

Some things don't come from code: a photo of the experimental setup, a
sketch you scanned, or measurements you took by hand. Say who made it.
If an AI tool helped, say which one. That's recorded against the person,
so someone always answers for it.
A PNG or PDF is exported from something, though, so for those, choose
**Exported** and give the file it came from.

Numbers can't be accounted for this way. A number in the paper should come
from something that computed it, so a measurement belongs in a dataset you
record as yours, and the number comes from a script that reads it.

## Run the pipeline and sync

Once a figure's origin is recorded, the project can make it. If the code
is on GitHub, Calkit can run the pipeline there; otherwise run it on your
computer with:

```sh
calkit run
```

<!-- Screenshot: img/overleaf-paper/sync.png
The "Sync now" prompt after a figure's origin is recorded. -->

Then click **Sync now** in the panel. Calkit sends the figure from the
project to the same place in your Overleaf project, replacing the copy that
was uploaded by hand, and the item is checked off. Your
`\includegraphics` line stays exactly as it was. If the figure is made
somewhere other than where the paper expects it, Calkit adds a step that
copies it into place, so you don't have to rename anything.

Numbers are different, since a number typed into the text has nothing to
point at. For those, Calkit swaps the typed value for a `\ckvalue`, which
reads it straight from the results file the script wrote, so it can't be
mistyped or left behind when the results change:

```latex
% Before
The fit has an RMSE of 0.12.
% After
The fit has an RMSE of \ckvalue[.2f]{results/fit.json}{rmse}.
```

`\ckvalue` comes from `calkit.sty`, which Calkit adds to your Overleaf
project along with a `\usepackage{calkit}` line in the preamble. The same
package has `\ckfigure` and `\cktable`, which the panel uses when you
insert a new figure or table from the project, but nothing you've already
written needs to change to use them.

From now on, putting the cursor on the figure shows what made it, whether
it's out of date, and a link to see it on calkit.io. When the code or data
changes, the figure shows as stale until you run the pipeline and sync
again.

<!-- Screenshot: img/overleaf-paper/provenance-card.png
The card shown with the cursor on an \includegraphics: stage, script,
inputs, and status. -->

## Repeat until nothing is left

Work down the checklist the same way. It gets faster as you go: once a
repository and its environment are connected, the next figure from the
same code is two clicks, and data files that several figures read only
need accounting for once.

You don't have to finish in one sitting. The checklist is saved with the
project, so you and your coauthors can pick it up where you left off.

## Release the paper for review

When the checklist is empty, you can release the paper for review. Calkit
checks that everything the paper shows can be traced all the way back,
builds the PDF, and gives you a link to share with reviewers. Figures and
numbers in the PDF link to where they came from, so a reviewer can see the
script and data behind any of them.

If anything is still unaccounted for, the release stops and says what, and
where it leads back to, e.g., a figure made from a data file nothing
records the source of.

<!-- Screenshot: img/overleaf-paper/release.png
Releasing the paper, and the shareable link. -->
