---
name: connect-overleaf-project
description: Connect an Overleaf project, e.g., a paper, thesis, or poster,
  to a Calkit project and the scripts and data behind it, so its figures and
  numbers come from a pipeline. Use when the user invokes
  `/calkit:connect-overleaf-project`, asks to connect an Overleaf project
  (often one open in their browser) to Calkit, or asks to make an Overleaf
  document reproducible. Not for only signing in to Overleaf.
---

# Connect an Overleaf project to its analysis

The person writes in Overleaf, e.g., a paper, thesis, or poster, and their
scripts and data are somewhere on their machine or a shared drive. The job is
to connect the two: a Calkit project with the document in it, stages that make
what the document shows, and the document reading those outputs instead of
pasted copies. The writing stays theirs. Change only how the document includes
figures and numbers.

Work in two places:

- **The browser**, through the person's own Overleaf session, for what only
  it can do: connecting the document, and checking the result in the editor.
  This needs a browser tool, e.g., Claude in Chrome.
- **A local clone**, through the CLI, for everything else.

Never type passwords or tokens. If something asks the person to sign in,
stop and ask them to do it.

## 1. Connect the document

In the Overleaf tab, open the Calkit panel from the launcher at the bottom
right, which reads "Calkit: not linked" when the document isn't connected. It's
in a shadow root, so it may not show in the page's accessibility tree; take a
screenshot to find it.

Click "Make this paper reproducible", check the project name, privacy, and
folder (e.g., `paper` or `thesis`), and create the project. The panel then
shows the project and "in sync". If the document should go in a project the
person already has, use "Use a project I already have" instead.

Without the browser extension, `calkit overleaf import URL paper` adds the
document to an existing local project, using Overleaf's Git access.

## 2. Clone it

```bash
calkit clone OWNER/NAME ~/calkit/NAME
```

`~/calkit/` is the usual place, unless the person keeps projects elsewhere.

## 3. Find what the document shows and where it came from

Read the document's `.tex` files and list:

- figures included from files in the document's folder, e.g., a pasted
  `\includegraphics{drag.png}`
- numbers typed into the text that are results, e.g., a mean or a fit
  parameter
- tables typed or pasted in

Then find the scripts and data that made them. Ask the person where they
keep their analysis before searching their files. Match a figure to its
script by its file name, `savefig` calls, axis labels, and data columns.
Don't move or delete anything in their folders; copy what the project needs.

## 4. Bring in the scripts and data

Copy scripts into `scripts/` and data into `data/`, then change paths in the
scripts to be relative to the project root. Where a number in the text comes
from a script, have the script write it to a results file, e.g.,
`results/drag.json`, rather than only printing it.

Add each script as a stage, previewing first:

```bash
calkit xr scripts/plot_drag.py --dry-run
calkit xr scripts/plot_drag.py
```

Check the detected inputs, outputs, and environment in `calkit.yaml`. Large
data belongs in DVC; see the conventions skill.

## 5. Have the document read the outputs

Load the package and swap each pasted figure and typed result for the
output that makes it:

```latex
\usepackage{calkit}
...
The mean drag coefficient was \ckvalue{results/drag.json}{mean_cd}.
\ckfigure[width=0.6\linewidth]{figures/drag.png}
\cktable{results/summary.tex}
```

Remove the pasted copies the document no longer includes, and drop them from
the LaTeX stage's `inputs`.

## 6. Say where everything starts

Data at the start of the chain needs an origin: `created_by` for data the
person measured or collected, or `imported_from` with a public URL or DOI
for data from elsewhere. A file on their laptop or a private drive isn't
somewhere it can be imported from. Ask the person which it is; don't guess.

```yaml
datasets:
  - path: data/drag_data_FINAL.csv
    title: Drag measurements
    created_by:
      - name: Their Name
        email: them@example.edu
```

A PNG or PDF can't be created by a person, since an app or script exports
it. If no script makes it, ask the person what they made it in.

## 7. Run, save, and sync

```bash
calkit run --save --overleaf -m "Make the drag figure from its script"
calkit check repro
```

Then, in the Overleaf tab:

1. Dismiss Overleaf's "Document Updated Externally" notice, if shown.
2. Reload the page, since the extension remembers what it last looked up.
3. Recompile, and check that no "Origin not defined" marks remain in the
   editor or on the PDF.
4. Hover a `\ckvalue` or `\ckfigure` to confirm it traces back to its stage
   and data.

Tell the person what you connected, what you asked them about, and anything
left without an origin.
