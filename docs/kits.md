# Kits

<!-- TODO: needs human review -->

A kit, short for calculation kit, is the part of a project that makes one
figure or document, packed inside that file.
Someone you send a figure to on Slack, or a reader who downloads your paper,
can see what made it, check the file hasn't changed since,
and expand it into a project they can run.

## Making one

```sh
calkit new kit figures/plot.png
```

This writes `plot.kit.png` in the current folder:
a copy of the figure with its kit inside.
The original is left alone.
The copy opens like any other PNG.

The kit holds the stage that makes the figure,
every stage upstream of it,
the scripts and environment specs they use,
and as much of their data as fits.
Data is added smallest first, inputs before intermediate outputs,
until the kit is as big as the figure itself or 1 MB,
whichever is bigger.
Use `--max-size` to change that, e.g., `--max-size 20MB`,
or `--no-data` to leave out all data.
Whatever is left out is still listed, with its hash,
so an expanded copy can fetch it from the project's storage
or remake it by running the pipeline.

The pipeline must be up to date, since a kit records how the file was made.
Use `--force` to make one anyway; the kit says it was out of date.
Changes that aren't committed are recorded too.

Kits leave out what describes your machine or isn't needed to run the
pipeline, e.g., Overleaf sync state and comments,
and credentials in Git remote URLs.
Everything else in the kit is visible to anyone with the file,
so check what's listed before sharing from a private project.

Releases can carry a kit too:

```sh
calkit new release --name fig-v1 --kit figures/plot.png
```

## Reading one

```sh
calkit describe plot.kit.png
```

This says which project and commit the file came from,
which stage made it,
whether the file is unchanged since the kit was made,
whether the pipeline was up to date,
which inputs have no recorded origin (see [provenance](provenance.md)),
and lists every file, marking those left out.
Add `--json` for tools.

`calkit describe` works on files in a project without a kit too,
saying what kind of artifact it is, which stage makes it,
whether that's up to date, and where its inputs came from.

## Expanding one

```sh
calkit expand plot.kit.png
```

This creates a project folder named after the original project,
with the figure in place, committed to a new Git repo.
The original project's Git remote is added as `upstream`,
so its full history can be fetched with `git fetch upstream`.
`calkit pull` fetches data left out of the kit, if you have access to the
original project's storage, and `calkit run` remakes outputs.

<!-- prettier-ignore -->
!!! warning

    A kit's pipeline is code.
    Look at what an expanded project runs before running it,
    as you would with any project you clone.

## Format

Kits are an open format, so other tools can read and write them.

A kit is a ZIP file with:

- `calkit-kit.json` at the root, the manifest
- the project files, under `project/`

The manifest follows a [JSON schema](schemas/calkit-kit.json).
It records:

- `kit_version`: currently `1`
- `artifact`: the file's path in the project, its size and SHA-256 without
  the kit, and the stage that makes it
- `source`: the project's name and title, Git remotes, commit,
  files with uncommitted changes, and whether the pipeline was up to date
- `files`: every file the pipeline uses, whether it's in the kit,
  where the project keeps it (`git` or `dvc`), its SHA-256 if it's in the
  kit, and DVC's MD5 if it's kept with DVC
- `provenance_gaps`: inputs with no recorded origin

The ZIP's entries have fixed timestamps, so the same project state makes the
same kit.

A file carries its kit in a way that leaves the rest of the file as it was,
so removing the kit gives back the original bytes,
which must match the manifest's `artifact.sha256`:

- **PNG:** a chunk of type `caLK` holding the ZIP, just before `IEND`.
- **PDF:** an attached file named `calkit-kit.zip`,
  added in an incremental update,
  so the original is the first `artifact.size` bytes.
- **SVG:** the ZIP as base64 inside
  `<metadata id="calkit-kit"><kit xmlns="https://docs.calkit.org/kits" version="1" encoding="base64">`
  and `</kit></metadata>`, just before the last `</svg>`.
- **HTML:** the ZIP as base64 inside
  `<script type="application/vnd.calkit.kit+zip;base64" id="calkit-kit">`
  and `</script>`, just before `</body>`.

The PNG chunk type marks it as ancillary, private, and unsafe to copy,
so image editors drop it when they change the image,
rather than keep a kit that no longer matches.
A PDF viewer lists the kit with the document's attachments.

Apps and websites that rewrite files, e.g., by compressing images,
may remove the kit.
