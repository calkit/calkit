# Environments

A computational environment describes the
necessary conditions for code to run properly.
Ensuring that every stage in your pipeline is run within a
defined environment is a great way to improve reproducibility.

Calkit provides a means for defining or declaring environments
in a project.
There is also a command line utility `calkit xenv`
for executing a command in one
of these, which ensures that the environment
matches its specification before execution.

## Environment types and definitions

Calkit supports defining and running code in these environment types:

- [Docker](https://docker.com)
- [Conda](https://docs.conda.io/projects/conda/en/stable/)
- [`venv`](https://docs.python.org/3/library/venv.html)
  (included in the Python standard library)
- [`uv`](https://docs.astral.sh/uv/) (both `venv` and project-based)
- [Pixi](https://github.com/prefix-dev/pixi)
- [`renv`](https://rstudio.github.io/renv/index.html)
- `ssh`

Environment definitions live in the project's `calkit.yaml` file
in the `environments` section.
Most environments will have a `path` property pointing to a file
that lists the necessary dependencies.
For example, a Python virtual environment or "venv" can be defined as
a simple list of dependencies in a `requirements.txt` file,
which might look like:

```
pandas>=2
polars==0.17.1
matplotlib
```

## Checking, syncing, and executing

A command can be executed in an environment with:

```sh
calkit xenv --name {env-name} -- {command}
```

Before the command is executed,
Calkit will check that the environment matches its specification,
and if it needs to be updated,
that will be done before execution.
Typically this will produce a "lock file" describing the exact
dependencies that made it into that environment
to help with diagnosing reproducibility issues down the road.

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

To create a new uv virtual environment,
inside a project directory run something like:

```sh
calkit new uv-venv -n my-env "polars>=1.0" matplotlib
```

This will create a new `uv` virtual environment called `my-uv-env` defined in
`requirements.txt` (changeable with the `--path` option),
with the packages installed under a folder `.venv`.

You can then run a command in this environment,
and since it doesn't exist yet, will be created and a file
`requirements-lock.txt` will be created.

```sh
calkit xenv -n my-env python -c "import matplotlib, print(matplotlib.__version__)"
```

If you were to run something like:

```sh
calkit xenv -n my-env python -c "import pandas, print(pandas.__version__)"
```

it would fail,
since `pandas` is not present in `requirements.txt`.
However, if you add it in there,
calling the above command again will succeed thanks to Calkit
automatically syncing the environment before execution.
The `requirements-lock.txt` file will also be updated.

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

### SSH

It's possible to define a remote environment that uses `ssh` to connect
and run commands,
and `scp` to copy files back and forth.
This could be useful, e.g.,
for running one or more pipeline stages on a high performance computing (HPC)
cluster,
or simply offloading some work to a virtual machine in the cloud
with specialized hardware like a more powerful GPU.

It is assumed that dependencies on the remote machine are managed separately.

An SSH environment defined in `calkit.yaml` looks like:

```yaml
environments:
  cluster:
    kind: ssh
    host: "10.225.22.25"
    user: my-user-name
    wdir: /home/my-user-name/calkit/example-ssh
    key: ~/.ssh/id_ed25519
    send_paths:
      - script.sh
    get_paths:
      - results
```

In the example above, we define an environment called `cluster`,
where we specify the host IP address, our username on that machine,
the working directory, the path to an SSH key on our local machine
(so we can connect without a password),
which paths we want to send before executing commands,
and which we want to copy back after they finish.
Wildcards in paths are supported, so the entire directory could be copied
if desired by specifying `*`.

To register an SSH key with the host, use `ssh-copy-id`. For example:

```sh
ssh-copy-id -i ~/.ssh/id_ed25519 my-user-name@10.225.22.25
```

To execute a command in this environment, we can add a stage like this
to our DVC pipeline in `dvc.yaml`:

```yaml
stages:
  run-simulation:
    cmd: calkit xenv -n cluster bash script.sh
    deps:
      - script.sh
    outs:
      - results
```
