# Installation

On Linux, macOS, or Windows Git Bash,
install Calkit and [uv](https://docs.astral.sh/uv/)
(if not already installed) with:

```sh
curl -LsSf install.calkit.org | sh
```

Or with Windows Command Prompt or PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm install-ps1.calkit.org | iex"
```

If you already have uv installed, install Calkit with:

```sh
uv tool install calkit-python
```

You can also install with your system Python:

```sh
pip install calkit-python
```

To effectively use Calkit, you'll want to ensure [Git](https://git-scm.com)
is installed and properly configured.
You may also want to install [Docker](https://docker.com),
since that is the default method by which LaTeX environments are created.
If you want to use the [Calkit Cloud](https://calkit.io)
for collaboration and backup as a DVC remote,
you can [set up cloud integration](cloud-integration.md) with:

```sh
calkit cloud login
```

If you use AI agents like Claude, Copilot, or Codex,
see [AI tools](ai-tools.md)
to learn how to install agent skills for working with Calkit.

## Use without installing

If you want to use Calkit without installing it,
you can use uv's `uvx` command to run it directly:

```sh
uvx calk9 --help
```

## Running against a specific version

If a project requires a Calkit version other than the one you have
installed, use the top-level `--use-version` flag to re-invoke the CLI
under that release without changing your installation:

```sh
calkit --use-version 0.38 run
```

This re-execs the CLI via `uvx --from calkit-python@<version> calkit`,
so it requires [uv](https://docs.astral.sh/uv/) on `PATH`.
You can also declare a minimum version in `calkit.yaml`;
see
[Pinning the Calkit CLI version](dependencies.md#pinning-the-calkit-cli-version).

## Calkit Assistant

For Windows users, the
[Calkit Assistant](https://github.com/calkit/calkit-assistant)
app is the easiest way to get everything set up and ready to work in
VS Code, which can then be used as the primary app for working on
all scientific or analytical computing projects.

![Calkit Assistant](https://github.com/calkit/calkit-assistant/blob/main/resources/screenshot.png?raw=true)
