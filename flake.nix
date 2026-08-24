{
  description = "Calkit: continuous delivery for research.";

  # Pin nixpkgs to a stable channel so all systems get a consistent uv
  # build. ``flake.lock`` next to this file fixes the exact revision.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # v1 packaging strategy: thin wrapper around ``uvx`` that runs the
      # published ``calkit-python`` wheel from PyPI. This trades the
      # ergonomics of a fully Nix-native build (which would require
      # tracking nixpkgs versions for ~30 runtime deps, plus working
      # around docx2pdf/appscript on macOS and the JupyterLab labextension
      # build) for something we can ship today with zero maintenance
      # drift. A full source build can replace this later; the public
      # interface (``packages.default``, ``apps.default`` named
      # ``calkit``) is meant to stay stable across that change.
      mkCalkit = pkgs: pkgs.writeShellApplication {
        name = "calkit";
        runtimeInputs = [ pkgs.uv pkgs.git pkgs.cacert ];
        text = ''
          # ``--from calkit-python`` pins the PyPI distribution; the bare
          # ``calkit`` console-script comes from inside that package. We
          # intentionally don't pin a version here so users get whatever
          # they last installed via ``uv tool`` cache, with the option to
          # override via ``CALKIT_VERSION``.
          if [ -n "''${CALKIT_VERSION:-}" ]; then
            exec uvx --from "calkit-python==''${CALKIT_VERSION}" calkit "$@"
          else
            exec uvx --from calkit-python calkit "$@"
          fi
        '';
      };
    in {
      packages = forAllSystems (pkgs: rec {
        calkit = mkCalkit pkgs;
        default = calkit;
      });

      apps = forAllSystems (pkgs: rec {
        calkit = {
          type = "app";
          program = "${self.packages.${pkgs.system}.calkit}/bin/calkit";
        };
        default = calkit;
      });

      # ``nix develop`` drops users into a shell that already has the
      # calkit CLI plus the system tools it commonly needs (git, uv).
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (mkCalkit pkgs)
            pkgs.git
            pkgs.uv
          ];
        };
      });
    };
}
