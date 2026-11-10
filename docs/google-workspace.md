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
You can connect more than one Google account, e.g., a personal one and a
work one, with **Connect another**,
but each can be connected to only one Calkit account.
Calkit uses whichever of them can open a presentation.
With more than one connected, choose which to create a presentation with,
or on the command line, use `--google-account` with its email.

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

## Working with collaborators

A presentation belongs to whoever created it in Google Drive,
but everyone with access to the project can use it.

- Each collaborator is given edit access to the presentation in Google
  Drive, when it's added to the project and when they join the project,
  so they can open it in Google Slides.
  It's shared with the email of the Google account they signed in to
  Calkit with, or otherwise their Calkit email.
- Running the pipeline goes through the Google account of whoever added the
  presentation to the project, so collaborators can export it and put
  figures in it without connecting their own Google account.
  If that person disconnects Google from Calkit,
  the project can't reach the presentation until they connect it again.

## Making a project public

Making a project public doesn't change who can see its presentations in
Google Slides; anyone can see the exported PDFs in the project.
To also let anyone with a presentation's link view it,
check **Also let anyone with the link view its Google Slides
presentations** when making the project public.
That includes its speaker notes and skipped slides,
which aren't in the exported PDF.
Making the project private again stops that.
