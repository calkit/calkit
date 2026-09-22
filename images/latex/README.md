# TinyTeX image

`ghcr.io/calkit/latex`: TinyTeX plus the packages journal classes and
recent papers need, and `latexdiff`, which comes to about 1.15 GB against
roughly 9 GB for `texlive/texlive:latest-full`.

It is what `calkit latex build` runs in when a document names no
environment of its own, and what Calkit's dev container and VS Code
settings use, and what new LaTeX environments are created with. All of
them pin an exact tag, set in `calkit/latex.py`,
`calkit/resources/vscode/settings.json`, and the dev container config
generated from it, and the docs' examples do the same.

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

The classes above turned out to be the smaller part of what documents
need. Of 175 recent arXiv papers across 16 categories, only 27 loaded
nothing that set lacked, and a quarter of them loaded `mathtools`.
Compiled in version 0.1.2, which had only that set, 5 of 48 of them
built.

`packages.txt` is the rest: every package those papers loaded that the
core lacks, plus what those packages load in turn, which only compiling
the papers shows, e.g., `tcolorbox`'s libraries need `tikzfill`, `pdfcol`
and `listingsutf8`, and `times` needs Courier for monospace text. With it
39 of the 48 build, for about 160 MB. It is installed in a layer of its
own so the core stays cached when the list changes.

Some things are left out on purpose, as too large for how rarely they're
used, and are better installed at run time by the documents that need
them: `cjk`, whose fonts are 90 MB for three papers in 175, `tex-gyre`,
and a few font families one paper used, e.g., `libertine` and `dejavu`.
Whole collections are no substitute either: the ones these papers draw
from would add over 600 MB and still leave a third of them unbuildable,
because the packages people load are spread across collections that each
carry far more than anyone uses.

`scan-arxiv.py` regenerates the list. It samples recent papers, checks
what they load against an image, and adds the TeX Live packages that
provide whatever's missing:

```sh
python scan-arxiv.py --image ghcr.io/calkit/latex:latest \
    --write packages.txt --exclude cjk libertine dejavu
```

It only sees what papers load directly, so compile a sample in the new
image afterwards and add whatever it asks for in turn. The smoke test
in `test-latex-image.yml` loads the most common of these, so trimming one
fails there.

The image tracks whatever `tlmgr` installs at build time rather than a
pinned TeX Live snapshot, so two builds of this Dockerfile on different
days can carry different package versions. That is why a project should
pin a tag rather than track `:latest`.

`latexdiff` is included because `calkit latex diff` needs it. It is a Perl
script, and the `perl` in the first layer is what makes it work here, on a
machine that may have no Perl of its own.

## Packages a document needs beyond this set

`calkit latex build` fetches them. When a build fails on a missing style,
class, or font file, it finds the TeX Live package that provides it,
installs it with `tlmgr --usermode`, and tries again, for as many rounds
as a package's own dependencies take.

What it fetches goes in the project, under the gitignored
`.calkit/local/texmf`, so nothing fetched can be committed, and each
project keeps what its documents need. That directory is inside the
working directory every container mounts, so nothing else is mounted:
Calkit sets `TEXMFHOME` to it when it runs this image itself, and when the
image runs as a Docker environment, including one built `FROM` it, the
entrypoint switches to it on finding `.calkit/local` in the working
directory. It leaves `TEXMFHOME` alone if something else set it.

Nothing is fetched into a system TeX, which is the user's to manage, or
in another image, where what's installed is gone when the container
exits.

A font's install ends with `tlmgr` reporting an error, since updating the
font map isn't possible in user mode here, but that comes after the font
files are in place, and TeX finds them. What decides whether a fetch
worked is the build that follows it.

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

It then opens a pull request moving the pinned tags, in the code and in
the docs' examples, to the new one. That pull request is opened with the workflow's own token, which
doesn't start other workflows, so its checks run only once someone pushes
to it or closes and reopens it.

The image is versioned on its own rather than with the Calkit release,
since it changes rarely.
