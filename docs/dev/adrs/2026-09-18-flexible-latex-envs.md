# Flexible LaTeX environments and installable prerequisites

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

Status: accepted, partially implemented.
Date: 2026-09-18.
Related: [#407](https://github.com/calkit/calkit/issues/407),
[#961](https://github.com/calkit/calkit/issues/961).

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

The resolved backend and its version are written to the environment's
lock file.
This is the part that matters for reproducibility: the lock, not the
resolver, is what a collaborator runs.
Someone who clones a project whose lock says Tectonic 0.15.0 gets
Tectonic 0.15.0, not whatever their own machine happens to resolve to
first.
Resolution runs when there is no lock; after that the lock is
authoritative, and a machine missing the locked backend is offered an
install of _that_ backend rather than being silently moved to a
different one.

Rejected: resolving on every run.
It would make the same project build through TeX Live on one machine and
Tectonic on another, which is precisely the class of difference that
reproducibility is supposed to rule out.

Rejected: explicit kinds only, with no `latex` kind.
It works, but it puts a research question ("which TeX distribution?") in
front of someone whose actual question is "does my paper build?".

When nothing is installed, the user is offered the options by name and
weight rather than having one chosen for them: Tectonic (tens of MB),
TinyTeX (hundreds), TeX Live (multiple GB, per decision 4), or Docker
(no local install, but pulls an image). Whatever they pick is what gets
locked.

### 2. Git and Docker join the installer registry (PR #1684)

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

**Unresolved, and deliberately flagged:** #1684 installs Git and Docker
automatically, including `curl -fsSL https://get.docker.com | sudo sh`
on Linux and Homebrew casks on macOS.
The policy chosen in the session that produced this ADR was the
opposite: register Docker, print the platform's own one-liner, and never
run a privileged or GUI installer off the back of a `[Y/n]`, on the
principle that Calkit may install into the user's own account without
ceremony but should not acquire root or launch a GUI installer because
someone pressed enter at a prompt.

Both are defensible -- the automatic path serves "install Calkit and
you're off to the races" most directly, and the assistant's whole job is
the machine that has nothing on it.
The two need reconciling before #1684 merges, since retrofitting a
consent policy after the fact is harder than deciding it now.

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

Windows is the sharp edge: TinyTeX there can install `latexdiff` through
`tlmgr`, but it still needs a Perl, which TeX Live's Windows bundle
provides and TinyTeX does not.
Docker remains the honest fallback for that case.

### 4. TeX Live is installable, but never the silent default

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

### 5. The Docker daemon check goes on the failure path

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

### 6. Rolling this out across two repos uses the version pin

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
