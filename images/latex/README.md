# TinyTeX image

Based on
[carteakey/tinytex-docker](https://github.com/carteakey/tinytex-docker),
the purpose of this image is to provide most of the packages scientific
articles need without the 9 GB of `texlive/texlive:latest-full`.
Instead, this one is about 1 GB,
which speeds up downloads.
When run through `calkit latex build`,
missing packages are installed into the project's `.calkit/local/texmf`
directory the first time they're needed.
It also includes `latexmk`, `latexdiff`, and other useful utilities.

This image is used by default for `calkit latex` commands,
new LaTeX environments,
and Calkit's dev container and VS Code settings.

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

Packages aren't installed automatically when running the image directly.
Instead, install missing ones into the mounted cache with:

```sh
docker run --rm -it \
    --user "$(id -u):$(id -g)" \
    -v "$HOME/.cache/calkit-texmf":/texmf \
    ghcr.io/calkit/latex:latest \
    tlmgr --usermode install <package>
```

The cache is only needed outside a Calkit project.
If the working directory contains `.calkit/local`,
the entrypoint sets `TEXMFHOME` to `.calkit/local/texmf` instead,
unless `TEXMFHOME` has already been set.

The cache mounts at `/texmf`, which is `TEXMFHOME`, and **not** over
`/opt/.TinyTeX`, where the distribution itself lives. Mounting anything
over the latter hides TinyTeX, leaving no `latexmk` or `pdflatex` in the
container at all. For the same reason the user tree is initialized by
`entrypoint.sh` at run time rather than in a build layer: a mounted cache
starts empty and would hide whatever the image had put there.

TinyTeX lives in `/opt` rather than `/root` so the image works when run
as the invoking user, which is how Calkit runs it so output isn't owned
by root. `/root` is `0700`, which left a non-root user with no TeX.

## For developers

### Rescanning arXiv for useful packages

`scan-arxiv.py` regenerates `packages.txt`.
It samples recent papers, checks what they use against an image,
and adds the TeX Live packages that provide whatever is missing:

```sh
python scan-arxiv.py --image ghcr.io/calkit/latex:latest \
    --write packages.txt --exclude cjk libertine dejavu
```

The excluded packages are large and rarely used,
so they're better installed when needed.
The script only finds packages that papers load directly,
so afterwards, compile a sample of papers with the new image and add any
dependencies that are still missing.
The smoke test in `test-latex-image.yml` loads the most common of these
packages,
so it will fail if one is removed.

The image tracks whatever `tlmgr` installs at build time rather than a
pinned TeX Live snapshot, so two builds of this Dockerfile on different
days can carry different package versions. That is why a project should
pin a tag rather than track `:latest`.

### Releasing

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
