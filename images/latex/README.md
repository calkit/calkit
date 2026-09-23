# TinyTeX image

`ghcr.io/calkit/latex` is TinyTeX plus the packages needed by journal
classes and recent papers, along with `latexdiff`.
It's about 1.15 GB,
compared with roughly 9 GB for `texlive/texlive:latest-full`.

This image is used by `calkit latex build` when a document has no
environment specified,
by Calkit's dev container and VS Code settings,
and for new LaTeX environments.
Each of these pins an exact tag,
set in `calkit/latex.py`, `calkit/resources/vscode/settings.json`,
and the dev container config generated from it.
The examples in the docs and the hub's environment preset also pin one.

Originally developed at
[`calkit/tinytex-latexmk-docker`](https://github.com/calkit/tinytex-latexmk-docker),
and based on [carteakey/tinytex-docker](https://github.com/carteakey/tinytex-docker).

## What's in it, and why that set

Whole TeX Live collections would make this a 5 GB image, which is barely
better than what it replaces. The packages here are instead the ones
real papers turned out to need, found by compiling a document in each
class against a bare TinyTeX and installing whatever it asked for.

Journal classes that build with nothing installed at run time:
Elsevier (`elsarticle`), APS (`revtex4-2`), IEEE (`IEEEtran`), ACM
(`acmart`), ACS (`achemso`), MNRAS, Springer LNCS (`llncs`), AMS
(`amsart`), and the JFM class that ships with its paper rather than
through TeX Live. The workflow builds one of each on every pull request,
so trimming a package that only one class needs fails there rather than
when someone submits a paper.

`revtex4-1` and `txfonts` are here because nothing could fetch them on
demand. `aastex631.cls` refuses to load without `revtex4-1` and stops
without TeX ever reporting a missing file, and `newtx` needs `txfonts`'
metrics, which surface as `Metric (TFM) file not found` rather than as a
missing `.sty`. Every other package here surfaces as a normal
`File 'foo.sty' not found`, which means a document needing something
else can install it at run time.

AASTeX itself is not built in CI, because its class isn't redistributable
here and isn't in TeX Live. `revtex4-1` was found by compiling a real
AASTeX paper against this image during development, so the support is
real but unguarded: removing `revtex4-1` would break AASTeX without
failing any test.

`cm-super` is here for a subtler reason. Elsevier and MNRAS ask for EC
fonts, which TeX Live otherwise carries only as bitmaps, so TeX
generates them at run time into `texmf-var` -- which the user running
the container may not be able to write to. With `cm-super` those fonts
exist as Type 1 and nothing is generated, which also makes for better
PDFs. `texmf-var` is writable anyway, for whatever else asks.

`siunitx`, `cleveref`, `algorithms` and `algorithmicx` are asked for by
documents rather than by any class: units, cross-references and algorithm
listings, which most papers need wherever they submit. About 110 kB
together.

## Packages papers load

It turns out the classes above are only a small part of what documents
need.
Of 175 recent arXiv papers across 16 categories,
only 27 used no packages outside that set,
and a quarter of them used `mathtools`.
With version 0.1.2, which only had that set,
5 of 48 sampled papers compiled.

`packages.txt` contains the rest:
every package those papers used that the core set doesn't include,
plus their dependencies,
which can only be found by compiling the papers,
e.g., `tcolorbox`'s libraries need `tikzfill`, `pdfcol`, and
`listingsutf8`, and `times` needs Courier for monospace text.
With these, 39 of the 48 papers compile, for about 160 MB.
They're installed in their own layer
so the core stays cached when the list changes.

Some packages are left out on purpose,
since they're large and rarely used,
so it's better to install them at run time for the documents that need
them.
These include `cjk`, whose fonts are 90 MB and were used by 3 of 175
papers, `tex-gyre`, and a few font families only one paper used, e.g.,
`libertine` and `dejavu`.
Installing whole collections instead would add over 600 MB and still
leave a third of the papers unable to compile,
since the packages people use are spread across collections that each
include far more than is needed.

`scan-arxiv.py` regenerates the list.
It samples recent papers, checks what they use against an image,
and adds the TeX Live packages that provide whatever is missing:

```sh
python scan-arxiv.py --image ghcr.io/calkit/latex:latest \
    --write packages.txt --exclude cjk libertine dejavu
```

It only finds packages that papers load directly,
so afterwards, compile a sample of papers with the new image and add any
dependencies that are still missing.
The smoke test in `test-latex-image.yml` loads the most common of these
packages,
so it will fail if one is removed.

The image tracks whatever `tlmgr` installs at build time rather than a
pinned TeX Live snapshot, so two builds of this Dockerfile on different
days can carry different package versions. That is why a project should
pin a tag rather than track `:latest`.

`latexdiff` is included because `calkit latex diff` needs it. It is a Perl
script, and the `perl` in the first layer is what makes it work here, on a
machine that may have no Perl of its own.

## Packages a document needs beyond this set

`calkit latex build` installs these automatically.
When a build fails because of a missing style, class, or font file,
it finds the TeX Live package that provides it,
installs it with `tlmgr --usermode`,
and tries again,
repeating as many times as needed to install the package's dependencies.

Packages are installed into the project in `.calkit/local/texmf`,
which is ignored by Git,
so each project keeps only what its documents need.
That directory is inside the working directory, which every container
already mounts, so no additional mounts are needed.
Calkit sets `TEXMFHOME` to it when running this image itself.
When the image runs as a Docker environment,
including one built `FROM` it,
the entrypoint sets `TEXMFHOME` if it finds `.calkit/local` in the working
directory,
unless `TEXMFHOME` is already set.

Packages are not installed into a system TeX distribution,
since that's for the user to manage,
or into other images,
where anything installed would be lost when the container exits.

Installing a font ends with `tlmgr` reporting an error,
since the font map can't be updated in user mode,
but the font files are already in place by then and TeX can find them.
Whether an install worked is determined by whether the next build
succeeds.

## Running it directly

```sh
mkdir -p "$HOME/.cache/calkit-texmf"

docker run --rm -it \
	--user "$(id -u):$(id -g)" \
	-v "$PWD":/work \
	-v "$HOME/.cache/calkit-texmf":/texmf \
	-w /work \
	ghcr.io/calkit/latex:latest \
	latexmk -pdf -cd paper/main.tex
```

The cache mounts at `/texmf`, which is `TEXMFHOME`, and **not** over
`/opt/.TinyTeX`, where the distribution itself lives. Mounting anything
over the latter hides TinyTeX, leaving no `latexmk` or `pdflatex` in the
container at all. For the same reason the user tree is initialized by
`entrypoint.sh` at run time rather than in a build layer: a mounted cache
starts empty and would hide whatever the image had put there.

TinyTeX lives in `/opt` rather than `/root` so the image works when run
as the invoking user, which is how Calkit runs it so output isn't owned
by root. `/root` is `0700`, which left a non-root user with no TeX.

## Releasing

Publish a release tagged `latex-image/vX.Y.Z`, the same way the other
subprojects are released, and the workflow builds it for amd64 and arm64
and pushes it to ghcr.io with a provenance attestation.

The workflow then opens a pull request to update the pinned tags in the
code, docs examples, and hub environment preset.
Since that pull request is opened with the workflow's own token,
which doesn't trigger other workflows,
its checks won't run until someone pushes to it or closes and reopens it.

The image is versioned on its own rather than with the Calkit release,
since it changes rarely.
