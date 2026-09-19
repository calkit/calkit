# LaTeX image

`ghcr.io/calkit/latex`, the image a LaTeX stage falls back to when the
machine has no TeX of its own. TinyTeX plus a curated set of packages and
`latexdiff`, which comes to about 766 MB against roughly 9 GB for
`texlive/texlive:latest-full`.

Originally developed at
[`calkit/tinytex-latexmk-docker`](https://github.com/calkit/tinytex-latexmk-docker),
and based on [carteakey/tinytex-docker](https://github.com/carteakey/tinytex-docker).

## What's in it, and why that set

Whole TeX Live collections would make this a 5 GB image, which is barely
better than what it replaces. The packages here are instead the ones a
real journal paper turned out to need, found by compiling an AASTeX 6.3.1
document against a bare TinyTeX and installing whatever it asked for.

`revtex4-1` is the one that has to be in the image rather than fetched on
demand. `aastex631.cls` refuses to load without it and stops without TeX
ever reporting a missing file, so nothing can discover it automatically.
Every other package here surfaces as a normal `File 'foo.sty' not found`,
which means a document needing something else can install it at run time.

`latexdiff` is included because `calkit latex diff` needs it. It is a Perl
script, and the `perl` in the first layer is what makes it work here, on a
machine that may have no Perl of its own.

## Packages a document needs beyond this set

Install them into the mounted cache rather than rebuilding the image:

```sh
tlmgr --usermode install <package>
```

A project says what it needs in `calkit.yaml`, and Calkit installs them:

```yaml
environments:
  tex:
    kind: tinytex
    packages:
      - fancyhdr
```

## Running it directly

```sh
mkdir -p "$HOME/.cache/calkit-texmf"

docker run --rm -it \
	-v "$PWD":/work \
	-v "$HOME/.cache/calkit-texmf":/root/texmf \
	-w /work \
	ghcr.io/calkit/latex:latest \
	latexmk -pdf -cd paper/main.tex
```

The cache mounts at `/root/texmf`, which is `TEXMFHOME`, and **not** at
`/root/.TinyTeX`, where the distribution itself lives. Mounting anything
over the latter hides TinyTeX, leaving no `latexmk` or `pdflatex` in the
container at all. For the same reason the user tree is initialized by
`entrypoint.sh` at run time rather than in a build layer: a mounted cache
starts empty and would hide whatever the image had put there.

## Releasing

Push a tag and the workflow builds and pushes it:

```sh
git tag latex-image/v1.0.0
git push origin latex-image/v1.0.0
```

The image is versioned on its own rather than with the Calkit release,
since it changes rarely, and `DEFAULT_LATEX_IMAGE` in `calkit/latex.py`
pins an exact tag. Bump that constant deliberately when a new image
should be the default, so an environment that resolved to Docker keeps
building against the same TeX until someone decides otherwise.
