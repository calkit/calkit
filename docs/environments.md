# Environments

A computational environment describes the
necessary conditions for code to run properly.
Ensuring that every stage in your pipeline is run within a
defined environment is a great way to improve reproducibility.
Typically these will be created inside the global system environment,
where the system environment has an environment manager installed.
Because the system environment itself is somewhat of a "primary artifact"
(cf. [reproducibility](./reproducibility.md)), i.e.,
it is manually manipulated by the user,
we want to minimize its uniqueness or changes to it,
since there's a risk we may not properly document its state.
This means we want to limit foundational dependencies to very common tools
like Git, common shells like Bash, and environment managers.

There are many different environment management tools out there to choose
from, and Calkit attempts to provide a similar interface for all of them.
Calkit also attempts to enforce
their usage in such a way that all important information about the environment
is captured locally in the project in so-called "lock files."
This way, the project can be moved to other machines
without needing to worry about manually installing packages.

Calkit provides a means for defining or declaring environments
inside a project's `calkit.yaml` file.
There is also a command line utility `calkit xenv`
for executing a command in one
of these, which ensures that the environment
matches its specification before execution.

## Environment types and definitions

Calkit supports the following environment types:

- [Docker](https://docker.com)
- [Conda](https://docs.conda.io/projects/conda/en/stable/)
- [`venv`](https://docs.python.org/3/library/venv.html)
  (included in the Python standard library)
- [`uv`](https://docs.astral.sh/uv/) (both `venv` and project-based)
- [Pixi](https://github.com/prefix-dev/pixi)
- [`renv`](https://rstudio.github.io/renv/index.html)
- [Julia](https://julialang.org/)
- [MATLAB](https://www.mathworks.com/products/matlab.html)
- [Nix](https://nixos.org/) (flake-based)
- [SLURM](https://slurm.schedmd.com/documentation.html)
- `system` (the machine itself, local or reached over SSH)

Environment definitions live in the project's `calkit.yaml` file
in the `environments` section.
Most environments will have a `path` property pointing to a file
that lists the necessary dependencies--the "spec."
For example, a Python virtual environment or "venv" can be defined as
a simple list of dependencies in a `requirements.txt` file,
which might look like:

```
pandas>=2
polars==0.17.1
matplotlib
```

## Automatic detection

For common environment types,
Calkit will register a new environment upon its first use with `calkit xenv`.
For example, if you run:

```sh
calkit xenv python scripts/run.py
```

Calkit will attempt to find an environment spec, create the environment,
save it in `calkit.yaml`, export a lock file,
and run the command in that environment.
If there are multiple env specs, e.g., `requirements.txt` and `environment.yml`,
you can provide the path, e.g.,

```sh
calkit xenv -p environment.yml python scripts/run.py
```

and Calkit will use that one to create the environment and save the path in
`calkit.yaml`.

## Checking, syncing, and executing

An environment can be checked that it matches its specification with:

```sh
calkit check env --name {env-name}
```

This will produce a "lock file"
(inside the project's `.calkit/env-locks`
directory if the environment manager doesn't export lock files by default),
which uniquely identifies the actual environment that was
created to help diagnose reproducibility issues down the road.

A command can be executed in an environment with:

```sh
calkit xenv --name {env-name} -- {command}
```

Before the command is executed,
Calkit will check that the environment matches its specification,
and if it needs to be updated,
that will be done before execution.

All project environments can be checked at once with:

```sh
calkit check envs
```

## Inspecting environment paths

To see where an environment's specification and lock file live, use:

```sh
calkit describe env --name {env-name}
```

Adding `--json` prints the same information as machine-readable JSON,
which is handy for other tools that need to locate these files:

```sh
calkit describe env --name {env-name} --json
```

The output is a single line, shown formatted here for readability
(pipe it through something like `jq` to format it yourself):

```json
{
  "kind": "uv-venv",
  "spec_path": "requirements.txt",
  "lock_path": ".calkit/env-locks/my-env/linux-64.txt",
  "prefix": null,
  "python": "3.13"
}
```

All keys are always present, so a null value means the field doesn't apply
to that kind of environment.
To describe every environment at once, keyed by name, use
`calkit describe envs [--json]`.

## Choosing an environment type

So which type of environment should you use?
The short answer is: any.
Any environment is better than none,
where none means installing dependencies in the global host machine
environment.
If you want the long answer, keep reading.

Docker is probably the most reproducible out of any environment type,
since a Docker image includes information about the operating system.
If it's convenient, e.g., if an image already contains all the necessary
dependencies, go with a Docker environment.
However, in some cases Docker may be a bit heavier than necessary.

If you're running Python code, a `uv-venv` environment is a good default choice.
`uv` is very easy to install and very fast.

If you have non-Python dependencies that depend on complex compiled binaries
(as scientific and engineering oriented tooling often does)
and a `uv-venv` can't be built on your machine,
A Conda environment is a good choice.
However, Pixi has access to the same packages and is a bit faster.
It's sort of like `uv` for Conda packages,
and is similarly very easy to install.

If you're working on a machine for which you don't have control to install
dependencies,
or working as part of a team,
a plain old Python `venv` could be the best option.

Again,
try not to get too hung up on the decision of which environment type to use.
Try one and see how it goes.
Calkit should make the experience similar for all types.

## Examples

Creating any type of environment from the Calkit CLI
follows a similar pattern starting with `calkit new`.
You can view the help output with `calkit new --help` and filter it down to
environment-related commands with `calkit new --help | grep env`.

### Docker

A new Docker environment can be added to the project with
`calkit new docker-env`.
A Docker environment can use an existing image,
e.g., from Docker Hub, or it can create a new image, e.g.,
from a `Dockerfile` stored in the project repo.

Let's say you want to add an OpenFOAM environment to your project.
This can be achieved with something like:

```sh
calkit new docker-env --image microfluidica/openfoam:2412 --name foam
```

Then you can run a command in that environment with:

```sh
calkit xenv -n foam -- icoFoam -help
```

You can similarly jump into an interactive `bash` terminal with:

```sh
calkit xenv -n foam bash
```

Some Docker images are CLI tools with an image entrypoint already defined
(for example `minlag/mermaid-cli`).
In that case, use `command_mode: entrypoint` so Calkit passes your command
arguments directly to the container entrypoint instead of running
`shell -c ...`.

```yaml
# In calkit.yaml
environments:
  mermaid:
    kind: docker
    image: minlag/mermaid-cli
    wdir: /data
    command_mode: entrypoint
```

Then execute with:

```sh
calkit xenv -n mermaid -- \
  -i figures/my-mermaid-diagram.mmd \
  -o figures/my-mermaid-diagram.pdf
```

But what if there isn't an image out there that has everything you need
already installed into it?
In this case, you can define and build a new derived image in the project
by using the `--from` parameter,
optionally adding predefined "layers" to the image with `--add-layer`.
This will produce a Dockerfile defining the image,
and when that environment is run with `calkit xenv`,
that image will be built and a lock file produced.

For example, running:

```sh
calkit new docker-env \
    --from microfluidica/openfoam:2412 \
    --name foam2 \
    --add-layer miniforge
```

will create a Dockerfile in the project and add the environment
named `foam2` to the `calkit.yaml` file.
Calling `calkit xenv -n foam2 bash` will cause the image to be built
and a lock file `Dockerfile-lock.json` to be created.
Note that the Dockerfile path can be controlled with the `--path` option.

You can go in and modify the Dockerfile, e.g.,
to add more installation commands,
and another call to `calkit xenv -n foam2` will kick off a rebuild
automatically,
since the lock file will no longer match the Dockerfile.

If you're copying local files into the Docker image,
you can declare these
dependencies in the environment definition so the content of those will be
tracked as well:

```yaml
# In calkit.yaml
environments:
  foam2:
    kind: docker
    image: foam2
    deps:
      - src/mySolver.C
```

This highlights Calkit's declarative design philosophy.
Simply declare the environment and use it in a pipeline stage
and Calkit will ensure it is built and up to date.
There is no need to think about building images as a separate step.

### uv

uv can create both _project_ and _venv_ virtual environments.
Project environments are defined by a `pyproject.toml` file,
while venv environments are defined by a `requirements.txt` file.

To create a new uv project environment,
inside a project directory run something like:

```sh
calkit new uv-env -n my-env "polars>=1.0" matplotlib
```

By default, this will create a `pyproject.toml` file in
`.calkit/envs/my-env/pyproject.toml`,
but the path can be controlled with the `--path` option.

To create a new uv venv,
simply replace `uv-env` with `uv-venv` in the above command and a
`requirements.txt`
file will be created instead.

```sh
calkit xenv -n my-env python -c "import matplotlib, print(matplotlib.__version__)"
```

If you were to run something like:

```sh
calkit xenv -n my-env python -c "import pandas, print(pandas.__version__)"
```

it would fail,
since `pandas` is not present in the spec file
(`pyproject.toml` or `requirements.txt`).
However, if you add it in there,
calling the above command again will succeed because Calkit
automatically checks or syncs the environment before execution.

### venv

A `venv` environment,
which uses Python's built-in `venv` module,
can be used nearly identically to the `uv` example above.
Simply replace `uv-venv` with `venv` in the `calkit new` call.

### Conda

As you might expect,
Conda environments again work nearly identically to `uv-venv` and `venv`
environments.

You can create a new Conda environment with something like:

```sh
calkit new conda-env -n my-conda-env numpy matplotlib --pip pandas
```

Note that in this case, we specified one package, `pandas`, to be
installed from the Python Package Index (PyPI)
with `pip` using the `--pip` option.

The new Conda environment spec will be written to `environment.yml`
by default,
which can be controlled with the `--path` option.

A prefix for the environment can be specified to keep all packages under the
project directory, e.g., by adding `--prefix .conda-envs/my-conda-env`.
If this option is omitted, the environment will become part of Conda's
system-wide collection of environments with a name like
`{project_name}-{env_name}`,
where the project name is added to avoid conflicts.

Similar to other environment types,
any time a command is executed with `calkit xenv`,
this environment will be checked and created or updated as necessary.

Calling:

```sh
calkit xenv -n my-conda-env -- which python
```

will create it.
If you add any dependencies to `environment.yml`,
calling that same command will cause the environment to be rebuilt
before execution,
and an updated `environment-lock.yml` file will be created.
Again this highlights Calkit's declarative design philosophy.
Declare the environment and what command should be executed inside,
and Calkit will handle the rest.

### Julia

[Julia](https://julialang.org/) environments have paths that point to a
`Project.toml` file.
Creating a new Julia environment is similar to creating a Python environment:

```sh
calkit new julia-env \
    --name my-julia-env \
    --path ./envs/my-julia-env/Project.toml \
    --julia 1.11 \
    WaterLily \
    Makie
```

With Julia environments, it's possible to execute a command:

```sh
calkit xenv -n my-julia-env -- -e "println(\"hello world\");"
```

or a script:

```sh
calkit xenv -n my-julia-env -- my_julia_script.jl arg1 arg2
```

Running Julia this was will ensure the global environment is ignored,
meaning you can be sure if it's successful on your machine,
it will be successful on others.

### SLURM

[SLURM](https://slurm.schedmd.com/documentation.html)
is a job scheduler commonly used for high performance computing (HPC).
A SLURM environment can be defined in `calkit.yaml` as follows:

```yaml
environments:
  my-hpc-cluster:
    kind: slurm
    host: hpc.myinstitute.org
```

See the [HPC guide](hpc.md) for how to use SLURM (and PBS) environments in pipeline stages.

### System

A `system` environment is the machine as it is,
with nothing built, installed, or isolated by Calkit.
It's an escape hatch for software Calkit doesn't manage,
e.g., a site-wide module system or a hand-built toolchain.

The simplest form is the machine you're on:

```yaml
environments:
  local:
    kind: system
    lock:
      - os
      - python-version
```

Nothing is pinned by default, since opting out of isolation is the whole
point of this kind.
The `lock` property is how a project says which properties of the machine
its results actually depend on.
Locked properties are written to the environment's lock file,
which stages depend on,
so moving to a machine where one of them differs reruns the stage
rather than silently reusing a cached result.
Run `calkit describe system` to see what's available to lock.

The built-in `_system` environment is shorthand for this kind
on `localhost` with nothing locked.

#### Running on another machine

A `system` environment's `host` names the machine the work belongs on.
SSH is how a machine is reached, not a kind of environment in its own
right, so there's no separate `ssh` kind:
if `host` names the machine you're on, the stage runs right there,
and otherwise Calkit connects over `ssh` and copies files with `scp`.
This is useful, e.g., for offloading work to a cluster login node
or a cloud VM with a more powerful GPU.

It is assumed that dependencies on the other machine are managed
separately, unless you pair it with an inner environment (see below).

```yaml
environments:
  cluster:
    kind: system
    host: "10.225.22.25"
    user: my-user-name
    wdir: /home/my-user-name/calkit/example
    key: ~/.ssh/id_ed25519
```

Here `wdir` is the project's _workspace_ on that machine---a clone of the
project, and the directory stages run in.
It's required to reach another host, since there's nowhere to put the
project otherwise.
`user` is the account to connect as, and `key` is the path to an SSH key on
this machine, so we can connect without a password.

To register an SSH key with the host, use `ssh-copy-id`. For example:

```sh
ssh-copy-id -i ~/.ssh/id_ed25519 my-user-name@10.225.22.25
```

To execute a command in this environment, we can add a stage like this
to our pipeline in `calkit.yaml`:

```yaml
pipeline:
  stages:
    run-simulation:
      kind: shell-script
      environment: cluster
      script_path: script.sh
      outputs:
        - results
```

#### How the workspace is kept in sync

Notice that nothing above says which files to copy back and forth.
Calkit works that out from the stage, because an environment doesn't know
what a stage reads, and a list maintained by hand falls behind the pipeline
sooner or later---at which point the stage quietly runs against stale
inputs, which is the failure you'd least want here.

Before the command runs, Calkit captures your working tree---including
edits you haven't committed---as a Git snapshot, pushes it straight to the
workspace, and checks it out there detached.
No branch is created on either side, so several people (or several clones)
can share one workspace without their branch names colliding, and cleaning
up afterwards is a single reserved namespace rather than a set of names
someone has to recognize.
Data that DVC tracks is ignored by Git, so it's sent separately, and only
the paths the stage actually declares as inputs.
Afterwards, the stage's declared outputs are copied back.

One consequence worth knowing: if the project changes locally while a stage
is running elsewhere, Calkit refuses to collect the results rather than
recording them.
DVC hashes a stage's dependencies from your local files once the command
returns, so recording a result in that situation would write a `dvc.lock`
pairing inputs that were never used with outputs they never produced---and
unlike a stale stage, which simply reruns, a lock file like that goes on
looking up to date indefinitely.

Note that `lock` can only be used when the host is the machine you're on.
Locking the properties of a machine Calkit can't observe would claim the
stage is pinned to something it isn't, so it's an error rather than a
silent no-op.

#### Pairing with a runtime

Because a `system` environment says _where_ a stage runs rather than what
it runs in, it can wrap another environment the same way a SLURM
environment can, using the composite `<outer>:<inner>` syntax:

```yaml
pipeline:
  stages:
    simulate:
      kind: python-script
      environment: cluster:py
      script_path: simulate.py
```

Calkit dispatches to `cluster` first, then activates the `py` environment
once there, so the workspace on that machine needs both Calkit and the
project.

### MATLAB

Adding a MATLAB environment to a project will cause Calkit to automatically
generate a Docker image based on its `version` and `products`
attributes.
A `MATLAB_LICENSE_SERVER` environmental variable must be set so the
container can properly contact a license server.
This can be done with:

```sh
calkit set-env-var MATLAB_LICENSE_SERVER <XXXX@some.server.edu>
```

Note that environmental variables set this way will be ignored by Git,
and so will need to be set on each new machine on which the project is to
be run.

A MATLAB environment (and a pipeline stage that uses it) looks like:

```yaml
# In calkit.yaml
environments:
  my-matlab-2024b:
    kind: matlab
    version: R2024b
    products:
      - Simulink
      - Global_Optimization_Toolbox
      - Parallel_Computing_Toolbox

pipeline:
  stages:
    my-matlab-script:
      kind: matlab-script
      script_path: scripts/run_sim.m
      environment: my-matlab-2024b
      inputs:
        - config/my-sim-config.json
      outputs:
        - results/sim-results.h5
```

### Pixi

Pixi environments typically have the path `pixi.toml`:

```yaml
environments:
  my-pixi:
    kind: pixi
    path: pixi.toml
```

### Nix

Calkit supports [Nix](https://nixos.org/) environments via
[flakes](https://nixos.wiki/wiki/Flakes).
Reproducibility comes from `flake.lock`, which pins every input (including
`nixpkgs`) to an exact revision. Calkit tracks `flake.lock` as a DVC
dependency, so pipeline stages re-run when the environment changes.

Create one with:

```sh
calkit new nix-env --name my-nix-env python3 R uv
```

In `calkit.yaml`:

```yaml
environments:
  my-nix-env:
    kind: nix
    path: flake.nix
```

Projects can contain multiple Nix envs. The first one lands at the repo
root (`flake.nix`); subsequent ones get nested under
`.calkit/envs/{name}/flake.nix` so each env has its own independent
`flake.lock`. You can override the path with `--path` if you want a
different layout.

To enter a specific dev shell from the flake (instead of the default),
set `shell`:

```yaml
environments:
  my-nix-env:
    kind: nix
    path: envs/my-nix-env/flake.nix
    shell: r-shell
```

Run a command in a Nix environment:

```sh
calkit xenv -n my-nix-env -- python --version
```

Add more packages to an existing Nix env (this edits the flake's
`packages = with pkgs; [ ... ]` list, refreshes `flake.lock`, and commits):

```sh
calkit update env --name my-nix-env --add-package R --add-package polars
```

On Linux and macOS, install Nix with `calkit install nix` — this runs the
[Determinate Systems installer](https://install.determinate.systems),
which enables flakes by default. Nix is not supported natively on
Windows; run Calkit inside
[WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) and install
Nix there.

Calkit itself is also available as a flake — see
[Nix in the installation guide](installation.md#nix) to add the Calkit
CLI to your own Nix environments via `inputs.calkit.url =
"github:calkit/calkit"`.

### R

R environments can be managed with Conda, Pixi, or `renv` (recommended).
The env spec path for an renv environment is typically a `DESCRIPTION` file.

```yaml
environments:
  r:
    kind: renv
    path: DESCRIPTION
```

The imports inside `DESCRIPTION` are used to create and sync the environment:

```
Package: CalkitProject
Version: 0.0.1
Title: Auto-generated R environment
Imports: tidyverse
```

## System environments

A `system` environment runs things on the machine as it is, with nothing
built, installed, or isolated.
It's the escape hatch for software Calkit doesn't manage, e.g., a site-wide
module system or a hand-built toolchain.

Nothing about the machine is pinned by default, since opting out of
isolation is the point of this kind.
`lock` is how a project says which properties its results actually depend
on:

```yaml
environments:
  cluster:
    kind: system
    host: gpu-node-1.example.edu
    lock:
      - os
      - julia-version
```

Locked properties are written to the environment's lock file, which stages
depend on, so running on a machine where one of them differs invalidates
the cached result instead of silently reusing it.
Locking a property the machine can't supply, e.g., a tool that isn't
installed, is an error rather than a recorded null---a stage that claims to
be pinned to something it isn't is worse than one that pins nothing.

<!-- prettier-ignore -->
!!! note
    The properties available to `lock` are a fixed set, so editors can offer
    them and a typo is reported rather than silently locking nothing. See
    the `system` entry in the reference below for the full list.

<!-- AUTO-GENERATED: ENV-KINDS:START -->

### Environment kind reference

Environment definitions belong in the `environments` section of `calkit.yaml`.

#### `conda`

Model class: `CondaEnvironment`

| Parameter   | Type             | Required | Description                              |
| ----------- | ---------------- | -------- | ---------------------------------------- |
| kind        | Literal['conda'] | yes      | What kind of environment this is.        |
| path        | str              | yes      | Path to the Conda environment YAML file. |
| prefix      | str              | no       | Path at which to create the environment. |
| description | str              | no       | A description of the environment.        |

#### `uv`

Model class: `UvEnvironment`

| Parameter   | Type          | Required | Description                              |
| ----------- | ------------- | -------- | ---------------------------------------- |
| kind        | Literal['uv'] | yes      | What kind of environment this is.        |
| path        | str           | yes      | Path to the uv project's pyproject.toml. |
| description | str           | no       | A description of the environment.        |

#### `venv`

Model class: `VenvEnvironment`

| Parameter   | Type            | Required | Description                                                                                                                                                                     |
| ----------- | --------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| kind        | Literal['venv'] | yes      | What kind of environment this is.                                                                                                                                               |
| path        | str             | yes      | Path to the requirements file, e.g., requirements.txt.                                                                                                                          |
| prefix      | str             | no       | Path at which to create the environment. If unset, this is resolved on the fly, defaulting to .venv next to the spec file, nesting under .calkit/envs/{name}/.venv on conflict. |
| python      | str             | no       | Python version to use when creating the environment.                                                                                                                            |
| description | str             | no       | A description of the environment.                                                                                                                                               |

#### `uv-venv`

Model class: `UvVenvEnvironment`

| Parameter   | Type               | Required | Description                                                                                                                                                                     |
| ----------- | ------------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| kind        | Literal['uv-venv'] | yes      | What kind of environment this is.                                                                                                                                               |
| path        | str                | yes      | Path to the requirements file, e.g., requirements.txt.                                                                                                                          |
| prefix      | str                | no       | Path at which to create the environment. If unset, this is resolved on the fly, defaulting to .venv next to the spec file, nesting under .calkit/envs/{name}/.venv on conflict. |
| python      | str                | no       | Python version to use when creating the environment.                                                                                                                            |
| description | str                | no       | A description of the environment.                                                                                                                                               |

#### `pixi`

Model class: `PixiEnvironment`

| Parameter   | Type            | Required | Description                                       |
| ----------- | --------------- | -------- | ------------------------------------------------- |
| kind        | Literal['pixi'] | yes      | What kind of environment this is.                 |
| path        | str             | yes      | Path to the Pixi manifest file.                   |
| name        | str             | no       | Name of the environment within the Pixi manifest. |
| description | str             | no       | A description of the environment.                 |

#### `docker`

Model class: `DockerEnvironment`

| Parameter      | Type                           | Required | Description                                                                                                                                       |
| -------------- | ------------------------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| kind           | Literal['docker']              | yes      | What kind of environment this is.                                                                                                                 |
| path           | str                            | no       | Path to the Dockerfile. Optional, since Docker environments can be defined purely by an image.                                                    |
| image          | str                            | yes      | Name of the Docker image.                                                                                                                         |
| layers         | list[str]                      | no       | Predefined layers to add to the generated Dockerfile.                                                                                             |
| shell          | Literal['bash'\|'sh']          | no       | Shell used to run commands in the image.                                                                                                          |
| command_mode   | Literal['shell'\|'entrypoint'] | no       | Whether commands run through a shell or the image's entrypoint.                                                                                   |
| platform       | str                            | no       | Platform to run as, e.g., 'linux/amd64'.                                                                                                          |
| wdir           | str                            | no       | Working directory inside the container. Defaults to '/work'.                                                                                      |
| user           | str                            | no       | User to run the container as. Defaults to the host user.                                                                                          |
| deps           | list[str]                      | no       | Files added to the container as dependencies.                                                                                                     |
| env_vars       | dict[str, str]                 | no       | Environmental variables to set in the container.                                                                                                  |
| ports          | list[str]                      | no       | Ports to expose, e.g., '8080:80'.                                                                                                                 |
| gpus           | str                            | no       | GPUs to make available, passed to 'docker run --gpus'.                                                                                            |
| args           | list[str]                      | no       | Extra arguments passed to 'docker run'.                                                                                                           |
| jupyter_kernel | str                            | no       | Name of the Jupyter kernel inside the image, used when executing notebooks with 'calkit nb execute'. Defaults to 'python3', or 'ir' for R images. |
| description    | str                            | no       | A description of the environment.                                                                                                                 |

#### `julia`

Model class: `JuliaEnvironment`

| Parameter   | Type             | Required | Description                               |
| ----------- | ---------------- | -------- | ----------------------------------------- |
| kind        | Literal['julia'] | yes      | What kind of environment this is.         |
| path        | str              | yes      | Path to the Julia project's Project.toml. |
| julia       | str              | yes      | Julia version to use.                     |
| description | str              | no       | A description of the environment.         |

#### `matlab`

Model class: `MatlabEnvironment`

| Parameter   | Type              | Required | Description                           |
| ----------- | ----------------- | -------- | ------------------------------------- |
| kind        | Literal['matlab'] | yes      | What kind of environment this is.     |
| version     | str               | no       | MATLAB version to use.                |
| products    | list[str]         | no       | MATLAB products (toolboxes) required. |
| description | str               | no       | A description of the environment.     |

#### `nix`

Model class: `NixEnvironment`

| Parameter   | Type           | Required | Description                                                                                                                          |
| ----------- | -------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| kind        | Literal['nix'] | yes      | What kind of environment this is.                                                                                                    |
| path        | str            | yes      | Path to the project's flake.nix. The flake.lock alongside it is the reproducibility-anchoring lock file tracked as a DVC dependency. |
| shell       | str            | no       | Name of the dev shell to enter, passed as #<shell> to 'nix develop'. Defaults to the flake's default dev shell.                      |
| description | str            | no       | A description of the environment.                                                                                                    |

#### `slurm`

Model class: `SlurmEnvironment`

| Parameter           | Type             | Required | Description                                                                                                                                                                                                                                                     |
| ------------------- | ---------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| kind                | Literal['slurm'] | yes      | What kind of environment this is.                                                                                                                                                                                                                               |
| host                | str              | no       | Host on which to submit jobs, over SSH if not localhost.                                                                                                                                                                                                        |
| default_options     | list[str]        | no       | Options passed to sbatch by default.                                                                                                                                                                                                                            |
| default_setup       | list[str]        | no       | Commands run at the start of every job script.                                                                                                                                                                                                                  |
| max_concurrent_jobs | int              | no       | How many of this project's jobs may sit in the queue (running or pending) at once. Submissions beyond the limit wait for a slot, so an iterated stage does not flood a shared cluster's queue with every one of its jobs at the same time. Null means no limit. |
| description         | str              | no       | A description of the environment.                                                                                                                                                                                                                               |

#### `renv`

Model class: `REnvironment`

| Parameter   | Type            | Required | Description                                                                       |
| ----------- | --------------- | -------- | --------------------------------------------------------------------------------- |
| kind        | Literal['renv'] | yes      | What kind of environment this is.                                                 |
| path        | str             | yes      | Path to the project's DESCRIPTION file. The renv lock file is created next to it. |
| prefix      | str             | no       | Path at which to create the environment.                                          |
| description | str             | no       | A description of the environment.                                                 |

#### `system`

Model class: `SystemEnvironment`

The machine as it is, with nothing built, installed, or isolated.

An escape hatch for software Calkit doesn't manage, e.g., a site-wide
module system or a hand-built toolchain. Nothing is pinned by default,
since opting out of isolation is the whole point of this kind, so
`lock` is how a project says which properties of the machine its
results actually depend on.

Locked properties are written to the environment's lock file, which
stages depend on, so moving to a machine where one of them differs
invalidates the cached result rather than silently reusing it.

`host` names the machine. SSH is how a machine is reached, not a kind
of environment, so there is no separate `ssh` kind: a system env whose
host isn't this machine is reached over SSH, and one whose host is this
machine runs here, the same way a SLURM env does. The built-in
`_system` environment is shorthand for this kind on `localhost`
with nothing locked.

`wdir` is the project's workspace on that host -- the directory the
stage runs in. It is required to reach another machine, since there is
nowhere to put the project otherwise.

What moves in and out of that workspace is deliberately not declared
here. An environment doesn't know which files a stage reads, so a list
kept alongside it can fall behind the pipeline and quietly run against
stale inputs; the paths are taken from the stage instead.

| Parameter   | Type                                                                                                                                                                                                                                                                                                                           | Required | Description                                                                                                                                                   |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| kind        | Literal['system']                                                                                                                                                                                                                                                                                                              | yes      | What kind of environment this is.                                                                                                                             |
| host        | str                                                                                                                                                                                                                                                                                                                            | no       | Host on which to run. Reached over SSH unless it names this machine.                                                                                          |
| user        | str                                                                                                                                                                                                                                                                                                                            | no       | User to connect as. Required to reach another host.                                                                                                           |
| key         | str                                                                                                                                                                                                                                                                                                                            | no       | Path to the SSH private key used to reach another host.                                                                                                       |
| wdir        | str                                                                                                                                                                                                                                                                                                                            | no       | The project's workspace on the host, in which stages run. Required to reach another host.                                                                     |
| lock        | list[Literal['os'\|'os-version'\|'platform'\|'machine'\|'processor'\|'hostname'\|'cpu-count'\|'memory-gb'\|'python-version'\|'python-implementation'\|'git-version'\|'docker-version'\|'conda-version'\|'mamba-version'\|'uv-version'\|'pixi-version'\|'julia-version'\|'juliaup-version'\|'rscript-version'\|'brew-version']] | no       | Properties of the machine this environment's results depend on. Stages rerun when a locked property changes. Empty means nothing about the machine is pinned. |
| description | str                                                                                                                                                                                                                                                                                                                            | no       | A description of the environment.                                                                                                                             |

<!-- AUTO-GENERATED: ENV-KINDS:END -->
