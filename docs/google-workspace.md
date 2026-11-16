<!-- TODO: needs human review -->

# Google Workspace integration

[Google Slides](https://slides.google.com) is a convenient place to make a
poster or a talk with collaborators, since it works in the browser with
nothing to install.
The catch is the same as with any document made outside the project:
figures have to be copied in by hand each time they change,
and the exported PDF easily falls out of step with the presentation.

With Calkit, a Google Slides presentation is part of the project.
The pipeline puts the project's latest figures into it,
exports it to a PDF, and keeps a PowerPoint copy,
and the export goes out of date when the presentation is edited in Google
Slides, just as it would when a script changes.

Google Docs and Sheets aren't supported yet.

## Connecting your Google account

Calkit reaches Google Slides through your Calkit account,
so connect Google there once:
in your [Calkit account settings](https://calkit.io/settings?tab=connected-accounts),
under **Connected accounts**, click **Connect** next to Google.

If you run a command that needs Google before connecting it,
Calkit opens that page for you and carries on once it's connected.

Calkit can only see the presentations it creates,
not the rest of your Google Drive.

Google asks which of your accounts to connect.
A work or school account's administrator may not allow apps like Calkit,
in which case Google says so; connect a personal account instead.
Only one Google account can be connected at a time.

## Creating a presentation

On the hub, open the project's **Presentations** page,
click **+**, and choose **New Google Slides presentation**.
Give it a title, whether it's slides or a poster,
and where the exported PDF should go in the project.
Calkit creates the presentation in your Google Drive,
adds it to the project,
and gives you a link to open it in Google Slides.

From the command line, the same thing is:

```sh
calkit new google-slides --title "My poster" --kind poster \
    --path poster/poster.pdf --figure figures/rates.png
```

To add a presentation you already have, use its URL:

```sh
calkit import google-slides https://docs.google.com/presentation/d/... \
    --path talk/talk.pdf
```

<!-- prettier-ignore -->
!!! note
    For now, Calkit can only open presentations it created,
    so importing works for a presentation created with Calkit,
    e.g., in another project.

## What's added to the project

The presentation itself stays in Google Drive.
The project gets the presentation, and a pipeline stage that exports it,
in `calkit.yaml`:

```yaml
presentations:
  - path: poster/poster.pdf
    title: My poster
    kind: poster
pipeline:
  stages:
    export-poster:
      kind: google-slides-export
      presentation_url: https://docs.google.com/presentation/d/.../edit
      inputs:
        - figures/rates.png
      outputs:
        - poster/poster.pdf
        - poster/poster.pptx
```

- `poster/poster.pdf` is the exported presentation.
- `poster/poster.pptx` is a PowerPoint copy, so the project keeps an editable
  version even without Google.
  Leave it out with `--no-pptx`.
- `.calkit/google/` records when each presentation was last edited,
  which is how Calkit knows an export is out of date.
  It's committed with the project.

## Putting project figures in a presentation

Each PNG, JPEG, or GIF figure in the stage's `inputs` is put into the
presentation before it's exported.
Add one with `--figure` when creating or importing the presentation,
or by adding it to `inputs` in `calkit.yaml`.

The first time, a figure is added to the first slide,
so move and resize it where it belongs.
After that, each run replaces it in place with the latest version,
keeping its position and size.
Calkit finds it by its alt text title, `calkit:` followed by the figure's
path, e.g., `calkit:figures/rates.png`,
so a figure can be shown in more than one place by copying it.
If no image has that title, e.g., because it was deleted,
the next run adds the figure to the first slide again.

## Showing results and tables

A text box or a table in a presentation can show a value or a table from
the project, filled in each time the pipeline runs,
like `\ckvalue` and `\cktable` in LaTeX.

- For a value, add a text box, then set its alt text title
  (right-click, **Alt text**, **Advanced options**, **Title**)
  to `calkit:`, the results file, `#`, and the key,
  optionally followed by `:` and a format, e.g.,
  `calkit:results/wake.json#mean_deficit:.2f`.
  Results files can be JSON, YAML, or TOML,
  and keys reach into nested values with dots, e.g., `case.score`.
  Formats are Python format specs, e.g., `.2f` for two decimal places.
- For a table, add a table, then set its alt text title to `calkit:` and a
  CSV or TSV file, e.g., `calkit:results/cases.csv`.
  Its cells are filled with the file's, header first,
  and rows and columns are added or removed to fit.

Each run replaces the text and keeps its style,
e.g., a value's font and size, or a table's colors,
and leaves alone what's already up to date.
Add the files to the stage's `inputs`,
so the presentation goes out of date when they change:

```yaml
pipeline:
  stages:
    export-poster:
      kind: google-slides-export
      presentation_url: https://docs.google.com/presentation/d/.../edit
      inputs:
        - results/wake.json
        - results/cases.csv
      outputs:
        - poster/poster.pdf
```

On the hub, a presentation lists the figures, values, and tables it shows.

## Making figures in Google Slides

A slide can also be a figure,
e.g., a diagram or a composite figure drawn in Google Slides,
exported to the project like any other, e.g., for a paper on Overleaf.
Open the slide in Google Slides, copy its URL,
which ends with `#slide=id.` and the slide's ID, and run:

```sh
calkit new figure figures/setup.pdf --title "Setup" \
    --google-slide "https://docs.google.com/presentation/d/.../edit#slide=id.g2c3a1b9_0_12"
```

The stage that exports the presentation, or a new one if there isn't one,
then exports the slide too:

```yaml
pipeline:
  stages:
    export-diagrams:
      kind: google-slides-export
      presentation_url: https://docs.google.com/presentation/d/.../edit
      slides:
        figures/setup.pdf: g2c3a1b9_0_12
```

- The figure is cropped to what's drawn on the slide, plus a small margin.
- It can be a PDF, or a PNG at 300 DPI.
- The slide's speaker notes say which figure it is, e.g.,
  `calkit:figures/setup.pdf`, so whoever edits the presentation can tell.
- Slides can be reordered, since they're found by ID.
  If the slide is deleted, the export says so,
  and names a slide whose notes still say which figure it is, e.g., a copy.
- A skipped slide can't be exported, since Google leaves it out of exports.

## Keeping the export up to date

Run the pipeline as usual:

```sh
calkit run
```

which checks Google Slides for edits first,
then puts the figures in and exports the presentation if anything changed.

`calkit status` and `calkit pull` also check whether presentations were
edited, so they show as out of date.
To only check Google, run:

```sh
calkit pull google
```

If you're offline, `calkit status` warns that it couldn't check,
and shows everything else as usual.
