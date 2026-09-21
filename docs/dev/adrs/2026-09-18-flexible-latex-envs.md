# Flexible LaTeX environments and installable prerequisites

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

Status: superseded in part on 2026-09-20; see "Scope cut" below.
Date: 2026-09-18.
Related: [#407](https://github.com/calkit/calkit/issues/407),
[#961](https://github.com/calkit/calkit/issues/961),
[#1695](https://github.com/calkit/calkit/pull/1695).

## Scope cut

Decisions 1 and 3 were not built. `kind: latex`, `kind: tectonic`,
backend resolution and ordering, diff-capability filtering, Tectonic
command translation, and the soft/hard lock split were all dropped
before merging, and the code implementing them was removed.

What shipped instead is the part that carries the benefit: the image,
and one environment kind, `tinytex-docker`, whose `packages` list is how
a project installs what the image doesn't ship. Both the image and the
packages are locked, since a missing TeX package fails a build rather
than changing how it looks.

The reasoning, from the pull request this came from: the 9 GB to 766 MB
reduction comes entirely from the image, while the flexible machinery is
where every sharp edge lives. The priority for that PR was the
quickstart -- getting someone to a working project quickly -- and a
smaller image serves it while backend resolution does not. Anyone who
wants to build with their own system TeX can still say so with a system
environment.

The sections below are kept for the evidence they record, which is
unchanged: the measurements, the two bugs in the image and how they were
found, and what a real journal paper needs to build. Read decisions 1
and 3 as a design that was considered and declined, not as what Calkit
does.

## Context

The goal this serves is stated plainly: install Calkit and you're off to
the races.
Setting up a system for high quality, sophisticated, reproducible
computational research should not require a day of prerequisites.

Today it does, and the quickstart shows where.
`calkit new project --template calkit/example-basic` finishes in about
25 seconds, but the first `calkit run` has to pull
`texlive/texlive:latest-full`, which is roughly 9 GB, and it can only do
that if Docker is already installed and its daemon is running.
The template's own `requirements` list names `docker` and `uv`, and
Calkit will happily tell a user that Docker is missing without being
able to do anything about it.
So the fastest path we advertise is gated on a multi-gigabyte download
behind a dependency we don't install.

Two things follow: a LaTeX stage should be able to build on a fresh
machine without Docker, and the prerequisites we do need should be
installable from the terminal a user is already in.

## Decisions

### 1. `kind: latex` resolves to an explicit backend, and the lock pins it

A flexible environment kind, `latex`, resolves a backend at run time in
priority order: system `latexmk`, then Tectonic, then TinyTeX, then
Docker.
`tinytex` and `tectonic` also become first-class environment kinds, so
resolution is a choice among real kinds rather than a hidden mode of one.
A project that wants to pin a backend names it directly and nothing is
resolved.

The resolved backend and its version are recorded, and by default that
recording is provenance rather than a pin.

This is the part that took the longest to settle, so the reasoning is
worth keeping. For a compute stage, the environment determines the
_result_: a different BLAS moves numbers, so the lock has to gate the
cache. For a document build it determines _typesetting_, while the
science arrives through the inputs -- the `.tex` source, the figures,
`results.tex` -- which are produced by upstream stages that stay
strictly locked. A backend swap changes kerning and line breaks, not
what the paper claims.

The strict guarantee is also partly illusory. `pdflatex` embeds
`/CreationDate` and a `/ID` by default, so two builds of identical
source on one machine already differ byte-wise unless
`SOURCE_DATE_EPOCH` and `FORCE_SOURCE_DATE` are set. Pinning the image
never bought byte-identical PDFs; it bought rebuildability, which is the
thing actually worth protecting.

So strictness is tiered, using vocabulary Calkit already has.
`system_env_locks_anything` (`calkit/environments.py:520`) already
decides whether a system environment writes a lock file at all, and an
environment that locks nothing gives its stages no dependency to hash.
A `latex` environment defaults to `lock: []`: nothing is pinned, no
stage dependency is added, and a collaborator with a different backend
does not rerun `build-paper` and commit a byte-different PDF into DVC.
Writing `lock: [backend]` or `lock: [backend, version]` opts into the
hard pin, exactly as a system env pins `os` or `python-version`, which
is what a camera-ready submission or an archived artifact should do.

This leaves one piece of new mechanism: with nothing locked there is no
lock file to carry the backend, so the backend and version have to be
recorded with the run's provenance instead. That is a feature, not a
workaround -- it is how a reader learns what produced the PDF without
the fact gating anyone's cache.

Calkit should also set `SOURCE_DATE_EPOCH` from the commit date when
building, which costs nothing and gets PDFs close to deterministic
within a backend.

Rejected: hard-locking the backend by default.
It buys a guarantee the toolchain does not honor, and charges for it in
DVC churn -- every collaborator on a different backend reruns the stage
and stores another PDF whose differences carry no scientific content.

Rejected: explicit kinds only, with no `latex` kind.
It works, but it puts a research question ("which TeX distribution?") in
front of someone whose actual question is "does my paper build?".

When nothing is installed, the user is offered the options by name and
weight rather than having one chosen for them: Tectonic (tens of MB),
TinyTeX (hundreds), TeX Live (multiple GB, per decision 5), or Docker
(no local install, but pulls an image). Whatever they pick is what gets
locked.

### 2. Invasive installs are prompted for, never automatic (PR #1684)

This is already built in
[#1684](https://github.com/calkit/calkit/pull/1684), which folds the
Calkit Assistant into the monorepo and expands `calkit/install.py` with
Homebrew, Chocolatey, Git, Docker, VS Code, Miniforge, and R.
It adds platform-specific entries (mac, linux, windows) with `unix` as
the fallback, a `requires` chain so Git and Docker on macOS pull in
Homebrew first, and a record of every install in
`~/.calkit/installed.json`.
No separate implementation is needed here; this ADR should not be read
as proposing one.

**The consent rule: an invasive install may be prompted for, never
performed automatically.**

Invasive means the install acquires root, writes outside the user's own
account, or launches a GUI installer -- `curl -fsSL
https://get.docker.com | sudo sh`, a Homebrew cask, `xcode-select`, a
distro package manager. Everything the registry carried before this
(pixi, uv, rustup, juliaup, nix) is user-local and not invasive.

Calkit may ask, and act on a yes. What it may not do is install one of
these as a side effect of something else the user asked for.

**And every prompt shows the exact command first, invasive or not.**
Consent to an unnamed action is not consent. This applies to the
user-local entries too: someone should be able to read
`curl -LsSf https://astral.sh/uv/install.sh | sh` and decide, or copy it
and run it themselves. Today the command is only revealed _after_ a
decline ("Skipped. To install, run: ..."), which is backwards -- it is
shown to the people who said no and hidden from the people who said yes.

Against that rule, #1684 is closer than it first appears, and an earlier
reading of it in this ADR was wrong. It does not install automatically:
it keeps the existing `prompt_and_install`, which asks `[Y/n]` on a TTY
and, when there is no TTY, prints the command and declines. Its
`requires` chain prompts for each prerequisite separately, with the
comment "saying yes to one thing never silently installs another" --
which is this rule, already implemented for the prerequisite case.

Three gaps remain, all small:

1. The prompt names neither the command nor the stakes. A `[Y/n]` that
   is about to run `curl | sudo sh` reads exactly like one that drops
   `uv` into `~/.local/bin`, and neither shows what will run. The prompt
   should print the command for every entry, and invasive entries should
   additionally be marked so the root, system-wide, or GUI part is
   stated rather than inferred. Roughly:

   ```
   Docker is not installed. Installing it needs root and affects
   the whole system:

     curl -fsSL https://get.docker.com | sudo sh

   Run this now? [y/N]
   ```

   Note the default flips to `N` for an invasive entry: a bare enter
   should not acquire root.

2. The `requires` loop calls `prompt_and_install(req, interactive=True)`
   with the flag hardcoded, so a non-interactive caller reaches an
   `input()` that only declines because `EOFError` is caught. It should
   pass the caller's own `interactive` through and take the
   non-interactive path deliberately.
3. `calkit install docker --yes` would run a privileged installer
   unattended. That is an explicit request naming the app, so it is
   consistent with the rule -- the prompt was answered on the command
   line -- but it is worth being deliberate about rather than incidental.

### 3. A backend is chosen for what the project does, not just compiling

A LaTeX stage is not only `latexmk`.
`calkit latex diff` marks up one revision against another with
`latexdiff` (`calkit/cli/latex.py:821`), and a `LatexStage` can carry
`diffs` that build those PDFs as part of the pipeline.
`latexdiff` is a Perl script that ships with TeX Live and is installable
into TinyTeX with `tlmgr`, but Tectonic has no equivalent and no Perl.

So backends differ in capability, not just in size, and resolving purely
on "can it compile?" would hand a paper that diffs to a backend that
cannot diff.
Each backend therefore declares whether it can run `latexdiff`, and
resolution takes the project into account: a project that diffs resolves
only among backends that can.
Ordering for a project that does not diff is system `latexmk`, Tectonic,
TinyTeX, Docker; for one that does, Tectonic drops out.

The capability belongs in the lock next to the backend, so a
collaborator who runs `calkit latex diff` on a project locked to
Tectonic gets a clear message rather than a `latexdiff: command not
found` from inside a container.
Note `_tex_cmd` already carries a `dep` argument naming the tool being
wrapped (`latexmk` or `latexdiff`), which is the natural place for this
to be enforced.

Perl turns out to be a much smaller problem than it looked.
`calkit/tinytex-latexmk-docker` already installs `perl` in its first
apt line, so making that backend diff-capable is adding `latexdiff` to
its `tlmgr install` list -- one word.
macOS and Linux have Perl in practice, and TeX Live on Windows bundles
its own.
The only real gap is a local TinyTeX on Windows, which is one registry
entry (Strawberry Perl) or a fall back to the image.

So the capability rule collapses to: Tectonic cannot diff, everything
else can.

Rejected: porting `latexdiff` to Python.
It is roughly ten thousand lines of Perl doing real TeX tokenization,
and its accumulated edge cases _are_ its value -- a partial port would
silently mis-mark diffs, which is worse than not having the feature.
With Perl already present everywhere that matters, there is nothing left
to buy.

### 4. Calkit ships its own image, and the existing one needs two fixes

`calkit/tinytex-latexmk-docker` is the right basis for a
"TeX Live full-ish" image: Ubuntu 24.04 plus TinyTeX, 756 MB on disk
(220 MB content) against roughly 9 GB for `texlive/texlive:latest-full`.
It should become the default image for LaTeX environments.

It now lives at `images/latex` in this repo and publishes as
`ghcr.io/calkit/latex`, following the dev container image already here:
built and smoke tested on pull requests, built multi-platform and pushed
with a provenance attestation on release. Being in the monorepo means a
change to the image can be tested against `calkit latex build` in the
same commit that makes it.

It is versioned on its own `latex-image/vX.Y.Z` tag rather than with the
CLI, since it changes rarely, and `DEFAULT_LATEX_IMAGE` pins an exact tag
rather than `:latest`. A floating tag would quietly undo the version
locking this ADR is built around: an environment that recorded a backend
version would go on building against whatever was pushed last.

It does not currently work, and testing found two independent reasons,
both reproduced here against a locally built copy.

**The documented invocation destroys the installation.** The README's
example mounts a host cache over the image's own TeX tree:

```sh
-v "$HOME/.cache/tinytex":/root/.TinyTeX
```

TinyTeX lives at `/root/.TinyTeX`, so an empty host directory shadows
it. Measured directly:

```
without the mount:  /root/bin/latexmk   /root/bin/pdflatex
with the mount:     MISSING
```

A persistent tree for on-the-fly packages has to be a separate one,
mounted somewhere that isn't the system tree. This was tested and
works:

```sh
docker run --rm \
    -v "$HOME/.cache/calkit-texmf":/root/texmf \
    -e TEXMFHOME=/root/texmf \
    ...
# in the container, once:
tlmgr init-usertree && tlmgr --usermode install <pkg>
```

All three properties hold: `latexmk` stays on `PATH` (nothing is
shadowed), `kpsewhich` resolves the installed package out of
`/root/texmf`, and the files persist on the host between runs.

**The minimal package set can't build a real journal paper.** Commit
71043e7 ("Remove packages from image") stripped the collections in
favor of `texliveonfly`. Building `boom-paper` (AASTeX 6.3.1,
`threeparttable`, `subfigure`, `rotating`, `todonotes`, `tikz`,
`epstopdf`, BibTeX via `aasjournal.bst`) from clean fails:

```
Please update your system to include revtex4-1.cls
(\end occurred when \ifx on line 3 was incomplete)
Latexmk: Log file says no output from latex
```

`aastex631.cls` loads `revtex4-1`, which was in the removed list. The
failure mode is the important part: the class prints its own message
and stops, so TeX never reports a missing file and `texliveonfly` has
nothing to act on. On-the-fly installation cannot rescue a class that
refuses to load, which is the flaw in the minimal-image strategy rather
than a bug in this particular image.

This was confirmed rather than reasoned about. A resolver loop written
for this investigation -- compile, read the missing file out of the
log, find its package with `tlmgr search --global --file`, install,
retry -- is a direct proxy for what `texliveonfly` does, and against
the minimal image it stops immediately with no missing-file error and
nothing to install. Seeding `revtex4-1` by hand is what gets it moving.

**Restoring the collections wholesale costs most of the advantage, and
is not necessary.** All three were built and tested against the same
paper:

| Image                             | On disk    | Builds the paper? |
| --------------------------------- | ---------- | ----------------- |
| `texlive/texlive:latest-full`     | ~9 GB      | yes               |
| seven collections (3,451 pkgs)    | 5.29 GB    | yes               |
| minimal (current `main`)          | 756 MB     | no                |
| **curated (12 pkgs + latexdiff)** | **766 MB** | **yes**           |

The collections' `tlmgr` layer alone is 3.17 GB, and 9 GB to 5.29 GB is
not the win this work is after.

The curated set was found by compiling `boom-paper` against the minimal
image and installing exactly what it asked for, one package at a time:

```
revtex4-1  textcase  epsf  ulem  threeparttable  multirow
units  grfext  subfigure  enumitem  todonotes  lineno
```

Twelve packages, 10 MB over the image that could not build anything at
all, and about a twelfth of what it replaces. Both the curated and
collections images produce the same 18-page document with no errors,
differing by 8 KB of font subsetting -- a typographic difference of
exactly the kind decision 1 treats as acceptable.

`revtex4-1` is the one that has to be baked in rather than fetched on
demand, for the reason above: its absence stops the class without
reporting a missing file. The other eleven are ordinary missing-file
cases that a resolver can find, which is what makes a project-declared
package list a workable escape hatch for whatever the core misses:

```yaml
environments:
  tex:
    kind: tinytex
    packages:
      - revtex4-1
      - epsf
```

That is what makes a small image viable, and it is why `packages` was
worth having on the explicit kinds. It also composes with the fix to
the cache bug above: a project's extra packages install into a
persistent `TEXMFHOME` tree on first run and stay there, so the cost is
paid once per machine rather than baked into the image for everyone.
The package list belongs in the environment spec, which means it is
version-controlled, and it is exactly the kind of thing that should be
locked, since a missing TeX package is a hard build failure rather than
a typographic difference.

### 5. TeX Live is installable, but never the silent default

TeX Live is what most people mean by "LaTeX on this machine", so the
registry should be able to install it -- a user who wants the
distribution they already know shouldn't have to leave the terminal for
it, and `calkit install texlive` is the obvious way to ask.

It is also the heaviest thing in the set, which is the whole reason this
ADR exists.
Installing it silently to satisfy a pipeline run would recreate the 9 GB
problem locally instead of in Docker.
So it is installable on request and offered by name when nothing else is
present, but it never wins an automatic resolution.

Per platform, verified where checkable:

| Platform | Full                                | Light                               |
| -------- | ----------------------------------- | ----------------------------------- |
| macOS    | `brew install --cask mactex-no-gui` | `brew install --cask basictex`      |
| Linux    | distro `texlive-full` (root)        | `texlive-latex-recommended`         |
| Windows  | `winget install TeXLive.TeXLive`    | MiKTeX, installs packages on demand |

The macOS casks were confirmed to exist (MacTeX 2026.0324, BasicTeX
2026.0301); `mactex-no-gui` is preferred over `mactex` since the GUI
apps are not what a pipeline needs.
The Windows and Linux identifiers still need checking on those
platforms.
Both a full and a light entry are worth registering: BasicTeX is roughly
two orders of magnitude smaller than MacTeX and takes `tlmgr install`
for whatever else a document needs, which makes it a reasonable default
for someone who wants a real TeX Live rather than Tectonic.

TeX Live earns its place for another reason: it is the only backend that
brings `latexdiff` and a Perl with it, so per decision 3 it is always
diff-capable, where Tectonic never is and TinyTeX needs `tlmgr install
latexdiff` plus a Perl it doesn't bundle on Windows.
A machine that already has `latexmk` on `PATH` is almost always a
machine with TeX Live, which is why the resolver prefers it and why
that preference costs nothing.

### 6. The Docker daemon check goes on the failure path

`docker --version` succeeds while the daemon is down, so "installed" and
"usable" are different questions, and the second one is what people
actually hit.
Probing it up front was measured at 1.6 seconds on a developer machine
with Docker running.
That is too much to add to every `calkit run` to catch a condition that
is already going to announce itself.
So the daemon is not probed during requirement checks; instead a Docker
failure is translated into a clear "Docker is installed but not
running" message at the point it fails.

### 7. Rolling this out across two repos uses the version pin

`example-basic` is a submodule at `examples/basic`, but
`calkit new project --template calkit/example-basic` clones that repo's
**main**.
A template change is therefore live for users of every Calkit version
the moment it merges, and there is no atomic merge spanning both repos.

The existing CLI version pin resolves this.
The template declares what it needs:

```yaml
requirements:
  - calkit>=X.Y
```

This was verified to fail in the right order: with `requirements`
naming a version the CLI doesn't satisfy and an environment of an
unknown kind in the same `calkit.yaml`, `calkit run` reports

```
Error: calkit>=99.0 required, but installed version is 0.47.5.
Re-run with 'calkit --use-version 99.0 ...' or upgrade with
'calkit upgrade'.
```

The requirement check runs before the environment is parsed, so an
older CLI gets an upgrade message rather than an unknown-kind error.

Sequence:

1. Land the LaTeX kinds in `calkit` and release.
2. In `example-basic`, switch the `tex` environment to `kind: latex`
   and add the `calkit>=X.Y` requirement in the same commit.
3. Rewrite the quickstart only once (2) is on main, so the docs never
   describe behavior the template doesn't have.

## Consequences

- A LaTeX stage no longer implies Docker, which removes the 9 GB
  download from the advertised fast path.
- A project's TeX backend becomes a locked, portable fact rather than a
  property of whoever ran it last.
- Backends stop being interchangeable: a project that diffs has a
  smaller set to resolve among, and that has to be visible rather than
  discovered when a diff fails.
- The docs quickstart is blocked on a release plus a change in another
  repo, which is worth saying out loud rather than discovering later.

## Open questions

- Which backend should win when several are present?
  Current order prefers an existing system `latexmk`, on the grounds
  that a machine that already has TeX Live should not download a second
  TeX.
- How should a locked backend that is absent and un-installable on a
  given machine degrade?
  Erroring is correct for reproducibility and annoying in practice; an
  explicit opt-in flag to re-resolve and re-lock is the likely answer.
- Tectonic can't currently serve matplotlib's `text.usetex`
  ([#961](https://github.com/calkit/calkit/issues/961)), so a project
  that needs that has to land on TinyTeX or Docker.
  Whether the resolver should know that, or whether it stays the
  project's job to pin, is unresolved.
