# Changelog

## 0.0.1

- Initial scaffold for a VS Code extension in `vscode-ext`.
- Added Calkit environment selection command for notebooks.
- Added nested Slurm + inner environment support with `--gpus`/`--time` prompts.
- Added stable notebook toolbar and command entry points for environment selection.
- Added environment preflight checks via `calkit check env -n <env>` before launch.
- Switched server launch to `calkit jupyter lab` and set `--ip=0.0.0.0` for Slurm launches.
- For `uv` and `julia` environments, now runs `calkit nb check-kernel -e <env>` so named kernels are available.
- For Slurm-outer launches, runs `calkit jupyter lab` directly under `srun` instead of wrapping with `xenv`.
- For non-nested `uv` and `julia` environments, no server is launched; kernel is registered and selected directly.
- Updated `uv` kernel registration to use `calkit nb check-kernel -e <env>` and skip any Jupyter server launch.
