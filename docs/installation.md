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

## Upgrading

Calkit checks for a new version once a day.
If it was installed with uv, as above, or pipx,
it upgrades itself in the background,
so your next command runs on the new version
and starts by telling you which version that is.
Otherwise, it tells you a new version is available.

To be told about new versions but not upgrade automatically, run:

```sh
calkit config set auto_upgrade false
```

To stop checking for new versions altogether, run:

```sh
calkit config set auto_upgrade no-check
```

To upgrade by hand at any time, run:

```sh
calkit upgrade
```

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

## Calkit Assistant

For Windows users, the
[Calkit Assistant](https://github.com/calkit/calkit/tree/main/assistant)
app is the easiest way to get everything set up and ready to work in
VS Code, which can then be used as the primary app for working on
all scientific or analytical computing projects.
Download the executable from the latest
[assistant release](https://github.com/calkit/calkit/releases?q=assistant%2Fv&expanded=true).

![Calkit Assistant](https://github.com/calkit/calkit/blob/main/assistant/resources/screenshot.png?raw=true)

## Windows Smart App Control

Smart App Control is a Windows 11 security feature
that blocks programs and libraries it can't verify,
either by a trusted signature
or by Microsoft's cloud-based reputation service.
Many of the files Calkit and Python environments rely on aren't signed,
e.g., the `calkit.exe` launcher uv creates,
the Python interpreters uv downloads,
and compiled modules in packages like pandas or h5py,
so Smart App Control may block them.
Since its decisions come from a cloud service,
a file that ran yesterday can be blocked today.

Signs that Smart App Control blocked something include:

- A "Part of this app has been blocked" notification from Windows Security,
  e.g., when VS Code starts Calkit.
- uv reporting that querying Python failed with exit status `0xc0e90002`.
- Python failing to import a compiled module with
  `An Application Control policy has blocked this file`.

Calkit links here when it sees one of these,
or when an environment fails to build while Smart App Control is on.
To see whether it's on, open Windows Security
and go to **App & browser control** > **Smart App Control settings**.
It only blocks files when set to **On**, not in **Evaluation** mode.

To get Calkit running again,
uninstall and reinstall it,
since `uv tool install --reinstall` can fail on the blocked Python
before it gets to reinstalling it:

```sh
uv tool uninstall calkit-python
uv tool install calkit-python
```

To rebuild a project environment with a blocked file, run:

```sh
calkit check env -n {environment name} --force
```

If blocks keep coming back,
turn Smart App Control off in the same settings page.
Depending on your version of Windows,
you may not be able to turn it back on without resetting Windows.
On a computer your organization manages,
an App Control policy set by your IT department can cause the same errors,
so ask them to allow the files instead.
