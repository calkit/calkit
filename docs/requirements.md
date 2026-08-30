# Requirements, configuration, and secrets

One major barrier to reproducibility is dependency management.
If one relies too much on system-level dependencies,
this can lead to reproducibility issues because a full system is hard to
define with sufficient detail.
Imagine trying to remember every change you've ever made to your computer
and determining which will impact running your project!

Our goal is then to minimize system-level dependencies and configuration
as much as possible,
and what remains should be generally applicable to many projects,
e.g., Docker, uv, and of course Calkit itself.
Conversely, relying on system-wide installations of things like
Python packages is a bad idea.
For software libraries and tools more specific to a project,
use [environments](environments.md).

Requirements can be declared in a project's `calkit.yaml` file
as a list in the `requirements` section,
and these will be checked before running the pipeline when
`calkit run` is called.
This way, when someone else tries to run your project,
they will be notified and can fix the issue before trying again,
which is more convenient than telling them to run through a
list of setup steps in a README.

A requirement can be an app, an environmental variable, a one-time setup
step, or a constraint on the machine itself, like how many CPUs it has.
Environmental variables are useful for configuration of a project that
needs to be unique on each user's machine,
which can also be used to avoid committing secrets to the repo.

<!-- prettier-ignore -->
!!! note

    This section used to be called `dependencies`, and that name still
    works, with a deprecation warning. It was renamed because half of
    what belongs here isn't something you can install: a CPU count or an
    amount of memory is required, not depended upon. Set one key or the
    other; setting both is an error, since they'd be two places for the
    same list to drift apart.

The example below, taken from
[this project](https://github.com/petebachant/strava-analysis)
shows both a unique configuration variable (`STRAVA_CLIENT_ID`)
and a secret (`STRAVA_CLIENT_SECRET`)
that allow a different user to use copy and reuse the project without
changing anything.

```yaml
requirements:
  - docker
  - name: STRAVA_CLIENT_ID
    kind: env-var
    notes: >
      The STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET environmental
      variables can be set in the .env file after creating a Strava
      application at https://www.strava.com/settings/api
  - name: STRAVA_CLIENT_SECRET
    kind: env-var
```

As we can see in the notes for `STRAVA_CLIENT_ID`,
a `.env` file, which is kept out of version control,
can be used to define these variables.
`calkit set-env-var` can be used as a shortcut to set one of these
in lieu of directly editing `.env`.
`calkit check env-vars` can also be run to check for missing variables,
prompting the user for their values and setting them in `.env`.

Additional (non-secret) environmental variables can be set at the project
level in `calkit.yaml` in the `env_vars` map:

```yaml
env_vars:
  MY_ENV_VAR_NAME: the-value-here
  ANOTHER_VAR: another value
```

These will then be set for calls to the `run` and `xenv` commands.

When `calkit run` (or `calkit check reqs`) encounters a missing
`env-var` requirement on an interactive terminal, it prompts the user
for a value, writes it to `.env`, and exports it for the rest of the
run.
`calkit status` does the same, except that a variable left unset is
reported rather than treated as fatal, since status reports rather than
enforces.

`calkit check reqs` is also available as `calkit check requirements`,
and, under the key's old name, as `calkit check deps` and
`calkit check dependencies`.
A per-variable `default` may be declared so that pressing Enter accepts
the default:

```yaml
requirements:
  - name: DB_URL
    kind: env-var
    default: postgres://localhost:5432/dev
```

In non-interactive contexts (CI), the same missing variable still
raises a clear error so failures aren't silent.

## Requiring something of the machine

Not everything a project needs is something you can install.
A simulation that needs a certain amount of memory to finish, or a stage
that divides work across cores, is making a claim about the machine
rather than about what's on it.
Those are written as a `kind` naming the property, with no name, since
`cpu-count` already says everything there is to say about which property
is meant:

```yaml
requirements:
  - kind: cpu-count
    min: 8
  - kind: memory-gb
    min: 32
  - kind: os
    equals: [Linux, Darwin]
  - kind: python-version
    version_spec: ">=3.11"
```

`cpu-count` and `memory-gb` take `min` and/or `max`.
Everything else takes `equals`---matched case-insensitively, and a list
means any one of them will do---or a `version_spec` for properties that
are versions.
The properties available are the machine-describing ones from the table
in [environments](environments.md#system);
versions of installed tools are reached as an `app` requirement with a
`version_spec` instead, which is one way to say it rather than two.

An entry that constrains nothing is rejected.
If you don't want to constrain a property but do want stages to rerun
when it changes, that's what a `system` environment's
[`lock`](environments.md#system) is for:
requirements gate, locks pin.

Checking these means reading the machine, which is what
`calkit describe system` reports.
A property the machine doesn't report is an error rather than a silent
pass---an unanswerable question isn't a satisfied one.

## Pinning the Calkit CLI version

A project can declare which version of the Calkit CLI it needs by
listing `calkit` itself as a requirement with a
[PEP 440](https://peps.python.org/pep-0440/) version specifier:

```yaml
requirements:
  - calkit>=0.38
```

Equivalent flat-dict form, useful when you want to add a `notes` field:

```yaml
requirements:
  - name: calkit
    kind: app
    version_spec: ">=0.38"
```

If the running CLI doesn't satisfy the spec, `calkit run` aborts with
a fix-it message pointing at two options: re-run against a pinned
version using `--use-version` (see below), or upgrade in place with
`calkit upgrade`.

### Running against a specific Calkit version

Use the top-level `--use-version` flag to re-invoke the CLI under a
specific `calkit-python` release without changing your installation.
This is the easiest way to bring a clone up to a working baseline:

```sh
calkit --use-version 0.38 run
```

Under the hood this re-execs as:

```sh
uvx --from calkit-python@0.38 calkit run
```

so it requires [uv](https://docs.astral.sh/uv/) (specifically `uvx`)
on `PATH`.
You can pass a bare version (`0.38`, treated as an exact pin) or a
PEP 440 specifier (`>=0.38`, `==0.38.1`, etc.).
Arguments after `--use-version <ver>` are forwarded to the child
process verbatim;
use `--` if you need to pass through a flag that would otherwise be
parsed by the parent (e.g. `calkit --use-version 0.3 -- --version`).

## Auto-installing apps

For a small set of well-known apps, Calkit ships with a registry of
upstream one-liner installers and can offer to run them when the app
is missing.
On an interactive terminal `calkit run` (and `calkit check reqs`)
will prompt before installing;
in CI the same path prints the install command as a fix-it and exits
non-zero.

Apps currently in the registry:

| Name               | Installer                                                                                          |
| ------------------ | -------------------------------------------------------------------------------------------------- |
| `pixi`             | `curl -fsSL https://pixi.sh/install.sh \| sh` (and PowerShell on Windows)                          |
| `uv`               | `curl -LsSf https://astral.sh/uv/install.sh \| sh`                                                 |
| `rustup`, `cargo`  | upstream `rustup` script on Unix, `winget` on Windows                                              |
| `juliaup`, `julia` | upstream `juliaup` script on Unix, `winget` on Windows                                             |
| `nix`              | [Determinate Systems installer](https://install.determinate.systems) on Unix; WSL2-only on Windows |

Run `calkit list installers` for the live list.

You can also trigger an install directly:

```sh
calkit install pixi          # prompts before running
calkit install pixi --yes    # non-interactive (scripts, CI provisioning)
```

After a successful install, Calkit prepends the installer's known
output directory (e.g. `~/.pixi/bin`) to `PATH` for the current
process, so the very next requirement check sees the new binary
without requiring a shell restart.

## Setup requirements

Some preconditions aren't files or environment variables -- they're
one-time per-machine actions like `gh auth login` or
`huggingface-cli login`.
The `setup` requirement kind captures these declaratively:

```yaml
requirements:
  - pixi
  - kind: setup
    name: Authenticate GitHub CLI
    check_command: calkit xenv -n analysis -- gh auth status
    setup_command: calkit xenv -n analysis -- gh auth login
    description: >
      Authenticate the GitHub CLI, which is used by the data-fetching
      stage of the pipeline. Run this once per clone; the pipeline can
      then pull data from GitHub without further prompts.
```

Each `setup` requirement declares:

- `check_command`: a shell command whose exit code determines whether
  the requirement is satisfied (exit `0` = satisfied). Required.
- `setup_command`: optional. On an interactive terminal Calkit asks
  before running it; in CI Calkit prints it as a fix-it and aborts.
- `description`: optional human-readable explanation; used in error
  messages and `calkit list`.
- `name`: optional. If omitted, Calkit synthesizes a stable name from
  a hash of `check_command`, so anonymous setup steps still get a
  predictable identifier in error messages.
- `cache_ttl`: optional. See below.

To run a `check_command` or `setup_command` inside one of the project's
environments, prefix it with `calkit xenv -n <env> --` explicitly --
there is no implicit wrap, because explicit is easier to debug when a
command fails.

### Caching setup checks

Probing a network-bound check (like `gh auth status`) on every
`calkit run` is wasteful and slow.
Calkit caches successful setup checks under
`.calkit/local/dep-checks.sqlite` (which is `.gitignore`d) for one day
by default.

The cache invalidates automatically whenever the `check_command` itself
changes, so editing `calkit.yaml` never silently relies on a stale
"passed" result.

To override the TTL for a single requirement, set `cache_ttl` to a duration
string (`30s`, `5m`, `2h`, `7d`, `1w`) or a bare integer number of
seconds.
`cache_ttl: 0` disables caching for that requirement:

```yaml
requirements:
  - kind: setup
    name: AWS credentials are valid
    check_command: aws sts get-caller-identity
    cache_ttl: 1h # re-check at most hourly
  - kind: setup
    name: Daily license check
    check_command: ./scripts/check-license.sh
    cache_ttl: 0 # always re-probe
```

To force a re-probe of every cached setup requirement on a single
invocation, pass `--no-cache`:

```sh
calkit check reqs --no-cache
```

## Ordering and the requirement flow

Within a single `calkit run` or `calkit check reqs`, Calkit processes
requirements in four phases regardless of the order they appear in
`calkit.yaml`:

1. **machine properties** -- first, because a machine too small to run
   the project at all should say so before anything is installed on it.
2. **`env-var`** -- prompted next so installers and setup steps can
   read newly-set variables.
3. **`app`** -- env managers like `pixi` and `uv` must exist before
   any setup step that runs inside one of those environments. Missing
   apps with a registered installer trigger the auto-install prompt
   here.
4. **`setup`** -- last, since `check_command` typically wraps
   `calkit xenv` and depends on both apps and env vars.

This ordering means a single fresh-clone `calkit run` can prompt for
secrets, install `pixi`, build the environment, and authenticate the
GitHub CLI without any manual setup steps in between.
