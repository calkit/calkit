# Calkit VS Code Extension

Use Calkit environments directly from VS Code Jupyter notebooks.

This extension lets you:

- Select notebook kernels backed by Calkit environments.
- Create new Calkit environments from VS Code (Conda, uv, Julia, and SLURM).
- Use nested environments like `slurm:main` for notebook jobs that, e.g., need to reserve GPUs on a cluster.
- Start, stop, and restart notebook server sessions for SLURM and Docker-backed workflows.
- Reopen notebooks and resume SLURM-backed sessions using toolbar actions.

## Features

From a notebook, you can manage both environment selection and kernel setup:

1. Open a Jupyter notebook.
2. Run **Calkit: Select Notebook Environment**.
3. Pick an existing environment or create a new one.
4. If needed, provide SLURM launch options (`--gpus`, `--time`, partition, extra flags).
5. Let the extension register/select the expected kernel and connect to the session.

For SLURM-backed notebook sessions, the notebook toolbar also provides:

- **Start Jupyter SLURM Job**
- **Stop Jupyter SLURM Job**
- **Restart Notebook Server**

## Requirements

- VS Code with the Jupyter extension installed.
- Calkit CLI available on your `PATH`.

If Calkit is missing or too old, the extension prompts with install/upgrade options.

## Environment mapping in `calkit.yaml`

When you select an environment for a notebook, the extension writes it to `calkit.yaml`.
It updates either `notebooks` or `pipeline.stages` depending on whether the notebook is part of a pipeline stage.

Example notebook mapping:

```yaml
notebooks:
  - path: my-notebook.ipynb
    environment: my-env
```

Example pipeline stage mapping:

```yaml
pipeline:
  stages:
    my-notebook:
      kind: jupyter-notebook
      notebook_path: my-notebook.ipynb
      environment: my-env
```

## Commands

- `Calkit: Select Notebook Environment`
- `Calkit: Create Environment`
- `Calkit: Start Jupyter SLURM Job`
- `Calkit: Stop Jupyter SLURM Job`
- `Calkit: Restart Notebook Server`
