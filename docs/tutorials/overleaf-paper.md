# Making an Overleaf paper reproducible

<!--
Outline only. Each section's comment says what it covers and which feature
it waits on; the comments come out as the prose goes in.
-->

## What you need

<!-- An Overleaf paper, the browser extension, a calkit.io account. -->

## Connect the paper to a project

<!--
"Make this paper reproducible" from the extension: creates a project on
the hub and links it to the Overleaf project.
Needs: project creation and Overleaf linking from the extension.
-->

## See what isn't accounted for

<!--
The extension lists every figure, table, and typed-in number the paper
shows with nothing recorded behind it, e.g., "7 of 12 figures accounted
for".
Needs: the provenance gap check, and the checklist on Overleaf.
-->

## Say where something came from

<!--
Point at one item and pick an answer. The fork in the road lives here.
-->

### Made by code in a GitHub repo

<!--
Connect the repo, pick the script and its environment, and get a stage.
Needs: connecting a repo from the extension, and building a stage and
environment from the answer.
-->

### Made by code on your computer

<!--
calkit new project in that folder (or the operator, once it lands), then
point to existing-project.md rather than repeating it.
-->

### Downloaded from somewhere

<!-- Records imported_from. -->

### Drawn or measured by you

<!-- Records created_by, with with_ai if an AI tool helped. -->

## Run the pipeline and sync

<!--
The \includegraphics becomes a \ckfigure and the item is checked off.
Needs: deciding who runs the pipeline for a GitHub repo (locally or
GitHub Actions), and converting \includegraphics to \ckfigure.
-->

## Repeat until nothing is left

## Release the paper for review

<!--
Where the strict provenance check runs. Needs #1819.
-->
