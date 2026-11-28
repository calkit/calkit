# Calkits

<!-- TODO: needs human review -->

A calkit, short for calculation kit, is the part of a project that makes one
figure or document, packed inside that file.
Someone you send a figure to on Slack, or a reader who downloads your paper,
can see what made it, check the file hasn't changed since,
and expand it into a project they can rerun.

## Creating one

```sh
calkit kit create figures/plot.png
```

This writes `plot.calkit.png` in the current folder:
a copy of the figure with its calkit inside.
The original is left alone.
The copy opens like any other PNG.
Add `--to-clipboard` to copy it, as a file, to paste into a chat or email.

Each calkit is recorded as a Git tag, e.g.,
`calkit/figures/plot.png/2026-11-27-1a2b3c4`,
at the commit it came from, and the tag is pushed,
so the project keeps track of what's been shared
without any of its files changing,
and the commit stays available to whoever has the calkit.
`calkit kit list` lists them.
Use `--no-record` to skip that.

The calkit holds the stage that makes the figure,
every stage upstream of it,
the scripts and environment specs they use,
and as much of their data as fits.
Data is added smallest first, inputs before intermediate outputs,
until the calkit is as big as the figure itself or 1 MB,
whichever is bigger.
Use `--max-size` to change that, e.g., `--max-size 20MB`,
or `--no-data` to leave out all data.
Whatever is left out is still listed, with its hash,
so an expanded copy can fetch it from the project's storage
or remake it by running the pipeline.

The pipeline must be up to date and committed,
since a calkit records how the file was made.
Use `--force` to create one anyway;
the calkit says it was out of date and lists uncommitted changes,
and one with uncommitted changes isn't recorded.

Calkits leave out what describes your machine or isn't needed to run the
pipeline, e.g., Overleaf sync state and comments,
and credentials in Git remote URLs.
Everything else in the calkit is visible to anyone with the file,
so check what's listed before sharing from a private project.

Releases can carry a calkit too:

```sh
calkit new release --name fig-v1 --kit figures/plot.png
```

## Reading one

```sh
calkit describe plot.calkit.png
```

This says which project and commit the file came from,
which stage made it,
whether the file is unchanged since the calkit was created,
whether the pipeline was up to date,
which inputs have no recorded origin (see [provenance](provenance.md)),
and lists every file, marking those left out.
Add `--json` for tools.

`calkit describe` works on files in a project without a calkit too,
saying what kind of artifact it is, which stage makes it,
whether that's up to date, and where its inputs came from.

## Expanding and rerunning one

```sh
calkit kit expand plot.calkit.png
```

This creates a project folder named after the original project,
with the figure in place, committed to a new Git repo.
The original project's Git remote is added as `upstream`,
so its full history can be fetched with `git fetch upstream`.
`calkit pull` fetches data left out of the calkit, if you have access to the
original project's storage, and `calkit run` remakes outputs.

```sh
calkit kit run plot.calkit.png
```

This expands the calkit, pulls inputs left out of it,
lists the commands its stages run and asks before running them,
reruns every stage, and checks the figure comes out identical.

```sh
calkit kit open plot.calkit.png
```

This expands the calkit, unless that's been done already,
and opens the project in your editor.
With `--hub`, it opens the original project on the hub instead,
at the commit the calkit came from.

<!-- prettier-ignore -->
!!! warning

    A calkit's pipeline is code.
    Look at what an expanded project runs before running it,
    as you would with any project you clone.

## Format

Calkits are an open format, so other tools can read and write them.

A calkit is a ZIP file with:

- `calkit-kit.json` at the root, the manifest
- `README.md` at the root, saying what the calkit is and how to use it
- the project files, under `project/`

The manifest follows a [JSON schema](schemas/calkit-kit.json),
whose URL it gives as `$schema`.
It records:

- `kit_version`: currently `1`
- `artifact`: the file's path in the project, its size and SHA-256 without
  the calkit, and the stage that makes it
- `source`: the project's name and title, Git remotes, commit,
  files with uncommitted changes, and whether the pipeline was up to date
- `files`: every file the pipeline uses, whether it's in the calkit,
  where the project keeps it (`git` or `dvc`), its SHA-256 if it's in the
  calkit, and DVC's MD5 if it's kept with DVC
- `provenance_gaps`: inputs with no recorded origin

The ZIP's entries have fixed timestamps, so the same project state makes the
same calkit.

Readers should treat a calkit from someone else as untrusted:

- Every path, in the ZIP and the manifest, is relative, uses `/`,
  has no empty, `.`, or `..` parts, and has no part named `.git` in any
  case.
  `.dvc/config.local`, `.dvc/tmp/`, and the DVC cache, besides directory
  listings, are left out.
- Every file under `project/` must be listed in `files` as included,
  once, with the same SHA-256, and every file listed as included must be
  there.
- A reader that finds a `kit_version` newer than it knows should refuse
  the calkit.
- Matching hashes show the file and the calkit agree with each other,
  not who made them, since both came in the same file.

A file carries its calkit in a way that leaves the rest of the file as it
was, so removing the calkit gives back the original bytes,
which must match the manifest's `artifact.sha256`:

- **PNG:** a chunk of type `caLK` holding the ZIP, just before `IEND`.
- **PDF:** an attached file named `calkit.zip`,
  added in one incremental update,
  so the original is the first `artifact.size` bytes.
  A file with more than one `%%EOF` after those bytes was saved again after
  the calkit was added, so it no longer matches.
- **SVG:** the ZIP as base64 inside a `<metadata id="calkit">` element,
  right before the last `</svg>`.
- **HTML:** the ZIP as base64 inside a
  `<script type="application/vnd.calkit+zip;base64" id="calkit">` element,
  right before the last `</body>`, in any case,
  or at the end of a fragment without one.

In SVG and HTML, the block is byte for byte the opening bytes,
a newline, the base64 with a newline every 76 characters,
then the closing bytes, with a comment linking here among the opening
bytes.
A file's own calkit is the block that ends right before that closing tag,
so a nested figure's calkit, earlier in the file, isn't mistaken for it.
Removing the calkit removes the whole block.
See `MARKUP_BLOCKS` in
[`calkit/kits.py`](https://github.com/calkit/calkit/blob/main/calkit/kits.py)
for the exact bytes.

The PNG chunk type marks it as ancillary, private, and unsafe to copy,
so image editors drop it when they change the image,
rather than keep a calkit that no longer matches.
A PDF viewer lists the calkit with the document's attachments.

Apps and websites that rewrite files, e.g., by compressing images,
may remove the calkit.
A file's `md5` is DVC's: the MD5 of its contents,
stored in DVC's cache under `files/md5/` with the first two characters as
a folder.
