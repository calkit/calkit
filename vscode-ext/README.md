# Calkit VS Code extension

In this VS Code extension we want to be able to support this flow:

1. Open notebook
2. Click "select kernel"
3. Click "Calkit environments..."
4. Create new Calkit environment: kind is SLURM --> enter name, host, default options like `--gpus`, `--time`.
5. Immediately create the inner environment: kind is Julia --> enter name, path to Project.toml, Julia version prefilled with currently detected Julia
6. The extension applies the nested `slurm:julia` environment to the notebook with SLURM options prefilled from defaults
7. Do some work
8. Click a stop button in the notebook toolbar to stop the srun job and free up the resources
9. Go away and close VS Code
10. Return and open the notebook, kernel is selected, but push a button in the notebook toolbar to start the slurm job for the kernel and connect to that

When an environment is selected for a notebook, it should either be done
in the `notebooks` or `pipeline` section of `calkit.yaml`,
depending on if the notebook has a pipeline stage.

```yaml
notebooks:
  - path: my-notebook.ipynb
    environment: my-env
```

or

```yaml
pipeline:
  stages:
    my-notebook:
      kind: jupyter-notebook
      notebook_path: my-notebook.ipynb
      environment: my-env
```

## Releasing

Publishing is handled by the GitHub Actions workflow at `.github/workflows/publish-vscode-ext.yml`.

1. Bump the version in `vscode-ext/package.json`.
2. Create a GitHub release whose tag is named `vscode-ext/vX.Y.Z` and matches that version.

The workflow installs dependencies, runs the extension tests, packages a `.vsix`, and publishes it to both the Visual Studio Marketplace and Open VSX.

Required repository secrets:

- `VSCE_PAT` for the Visual Studio Marketplace publisher token
- `OVSX_PAT` for the Open VSX access token
