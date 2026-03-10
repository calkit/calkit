# Calkit Notebook Environments (VS Code)

This extension adds a Calkit-first notebook kernel selection flow for VS Code Jupyter notebooks.

## MVP scope

- Adds `Calkit: Select Notebook Environment` command.
- Contributes a notebook toolbar action and command palette command.
- Lists notebook-capable environments from `calkit.yaml`.
- Supports nested choices like `<slurm-env>:<inner-env>`.
- Prompts for `srun` options including `--gpus` and `--time` for nested Slurm launches.
- Runs `calkit check env -n <inner-or-main-env>` before launching Jupyter.
- Registers kernels for `uv` via `calkit nb check-kernel -e <env>` and auto-selects them in VS Code.
- Registers kernels for `julia` via `calkit nb check-kernel -e <env>` and auto-selects them in VS Code.
- Starts a Jupyter server command in a dedicated terminal and copies the URI.

## Current behavior

1. Open a notebook in a Calkit project.
2. Run `Calkit: Select Notebook Environment` from command palette or notebook toolbar.
3. Pick an environment.
4. If it is nested with Slurm, provide optional `srun` flags.
5. The extension launches the server command in terminal `Calkit Notebook Server`.
6. Use `Notebook: Select Notebook Kernel` (or `Select Kernel` button in the prompt) to pick the kernel.

## Notes

- This initial implementation launches commands via `calkit xenv` and `srun`.
- Jupyter launch uses `calkit jupyter lab`; nested Slurm launches add `--ip=0.0.0.0` and run server directly under `srun`.
- For `uv` selections, the extension only checks/registers kernel and selects it (no Jupyter server launch).
- For remote Slurm hosts, you may need to connect to the host first.
- Follow-up versions can call richer Calkit/JupyterLab backend endpoints for tighter lifecycle and kernel auto-selection.
