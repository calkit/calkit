# Using Calkit with JupyterLab

Calkit includes a [JupyterLab](https://jupyter.org/)
extension for managing a project's environments and pipeline.
Installing Calkit will install JupyterLab itself as well,
so you can start it up with:

```sh
cd my-project-folder
calkit jupyter lab
```

With the extension, you won't need to remember to:

1. Fully document the environment for a notebook.
2. Ensure each notebook was run top-to-bottom any time its code or input
   files (e.g., datasets) have change.

Further, it will be obvious if any notebook outputs, e.g.,
figures, are out-of-date and require a rerun.
