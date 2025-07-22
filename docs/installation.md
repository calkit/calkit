# Installation

To install Calkit, [Git](https://git-scm.com) and Python must be installed.
If you want to use [Docker](https://docker.com) containers,
which is typically a good idea,
that should also be installed.
For Python, we recommend
[uv](https://docs.astral.sh/uv/).
On Linux, macOS, or Windows Git Bash, you can install Calkit and uv with:

```sh
curl -LsSf https://github.com/calkit/calkit/raw/refs/heads/main/scripts/install.sh | sh
```

Or with Windows Command Prompt or PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://github.com/calkit/calkit/raw/refs/heads/main/scripts/install.ps1 | iex"
```

If you already have uv installed, install Calkit with:

```sh
uv tool install calkit-python
```

Alternatively, but less ideally, you can install with your system Python:

```sh
pip install calkit-python
```

Next,
[connect to a Calkit Hub](cloud-integration.md)
for collaboration and backup.

## Calkit Assistant

For Windows users, the
[Calkit Assistant](https://github.com/calkit/calkit-assistant)
app is the easiest way to get everything set up and ready to work in
VS Code, which can then be used as the primary app for working on
all scientific or analytical computing projects.

![Calkit Assistant](https://github.com/calkit/calkit-assistant/blob/main/resources/screenshot.png?raw=true)
