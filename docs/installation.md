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
If you want to use a [Calkit hub](hub/index.md)
for collaboration and backup as a DVC remote,
you can [connect to the hub](hub/index.md) with:

```sh
calkit hub login
```

If you use AI agents like Claude, Copilot, or Codex,
see [AI tools](ai-tools.md)
to learn how to install agent skills for working with Calkit.

## Use without installing

If you want to use Calkit without installing it,
you can use uv's `uvx` command to run it directly:

```sh
uvx ck9 --help
```

## Nix

Calkit ships a [flake](https://nixos.wiki/wiki/Flakes) at the root of
its repo, so [Nix](https://nixos.org/) users can pull the CLI into their
environments alongside their other tools.

Run it ad hoc without installing:

```sh
nix run github:calkit/calkit -- --help
```

Drop into a shell that has `calkit`, `git`, and `uv` on `PATH`:

```sh
nix shell github:calkit/calkit
```

Add it to your own `flake.nix` as an input:

```nix
{
  inputs.calkit.url = "github:calkit/calkit";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs, calkit }: {
    devShells.x86_64-linux.default =
      nixpkgs.legacyPackages.x86_64-linux.mkShell {
        packages = [ calkit.packages.x86_64-linux.default ];
      };
  };
}
```

Then `nix develop` will give you a shell with the Calkit CLI ready to
use. To pin a specific Calkit release inside the shell, set the
`CALKIT_VERSION` environment variable (e.g. `CALKIT_VERSION=0.41.0`)
before invoking `calkit`.

The flake is currently a thin wrapper around `uvx --from calkit-python
calkit`. It depends on `uv` from `nixpkgs` and fetches the published
wheel from PyPI on first use. This trades a fully Nix-native build for
zero version-drift maintenance, and avoids the macOS `docx2pdf` /
`appscript` and JupyterLab labextension build issues that block a pure
nixpkgs derivation today. If you want a fully nixpkgs-native build,
see the community [`calkit-nix`](https://github.com/dwinkler1/calkit-nix)
flake.

Nix isn't supported natively on Windows; run Calkit inside
[WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) and use
the flake there.

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
[Pinning the Calkit CLI version](requirements.md#pinning-the-calkit-cli-version).

## Line endings on Windows

Windows writes CRLF line endings where macOS and Linux write LF, and Git
rewrites text files on checkout to match when `core.autocrlf` is on, which
is the default for Git for Windows. DVC hashes files as they are on disk,
so the same file can hash differently on two machines and a stage that
nobody touched reads as stale.

Calkit pins the line endings of its own generated files---the environment
lock files and import records under `.calkit`---with a managed block in
`.gitattributes`, so those are safe whatever your Git configuration says.

Files your project itself commits are your call, and DVC's
[guidance for running on Windows](https://doc.dvc.org/user-guide/how-to/run-dvc-on-windows)
covers them. Their recommendation, for a project worked on from more than
one platform:

```sh
git config --global core.autocrlf false
git config --global core.eol lf
```

<!-- prettier-ignore -->
!!! note

    Adding a `.gitattributes` rule to a repository that already has CRLF
    files committed makes Git renormalize them on the next checkout, so
    expect one commit's worth of churn as they settle.

## Calkit Assistant

For Windows users, the
[Calkit Assistant](https://github.com/calkit/calkit-assistant)
app is the easiest way to get everything set up and ready to work in
VS Code, which can then be used as the primary app for working on
all scientific or analytical computing projects.

![Calkit Assistant](https://github.com/calkit/calkit-assistant/blob/main/resources/screenshot.png?raw=true)
