# SLURM integration

Calkit can run pipeline stages on a SLURM job scheduler
using the `slurm` environment kind.
The `calkit slurm` CLI can then be used to monitor these jobs
by their name in the context
of a project.

For example, let's create a `calkit.yaml` file with a `slurm` environment
and two `sbatch` stages:

```yaml
# In calkit.yaml
environments:
  my-cluster:
    kind: slurm
    host: my.cluster.somewhere.edu

pipeline:
  stages:
    sim:
      kind: sbatch
      environment: my-cluster
      script_path: scripts/run-sim.sh
      inputs:
        - config/my-sim-config.yaml
      outputs:
        - results/all.h5
      slurm:
        options:
          - --time=60
    post-process:
      kind: sbatch
      environment: my-cluster
      script_path: scripts/post.sh
      inputs:
        - results/all.h5
      outputs:
        - results/post.h5
        - figures/myfig.png
      slurm:
        options:
          - --gpus=1
          - --time=20
```

When calling `calkit run`, as long as we're running from the project
directory on the host
`my.cluster.somewhere.edu`,
the `run-sim` job will be submitted.
By default, Calkit will wait for the job to finish, but will be robust
to disconnecting.
That is, if you disconnect and reconnect (or simply exit with `ctrl+c`),
calling `calkit run` will check if the job is still running and wait
for it if so.

If we wanted to submit both jobs at the same time, we could call
`calkit run sim`, press `ctrl+c` to stop waiting,
then call `calkit run post-process`.

If we want to check the status of any of the project's jobs, we can
call `calkit slurm queue`,
and if we wanted to cancel one,
we can cancel it by name, e.g.,
`calkit slurm cancel post-process`.

## Running non-shell (Python, Julia, R) scripts and notebooks

It's also possible to run Python, Julia, or R scripts in their respective
environments within a SLURM "outer" environment using a nested environment
syntax.
Setting up stages this way will ensure the inner environments match their spec
before running, and negates the need to activate them before running the
job, or writing a shell script that creates and/or activates them.
These pipeline stages will also be robust to SSH disconnects from the cluster
and their outputs will be cached, which will be invalidated if any inputs
are changed, just like any other pipeline stage.

Here's a simple example that uses a Conda environment to run a Python script
and Jupyter notebook:

```yaml
# In calkit.yaml
environments:
  my-cluster:
    kind: slurm
    host: my.cluster.somewhere.edu
  my-conda-env:
    kind: conda
    path: environment.yml

pipeline:
  stages:
    sim:
      kind: python-script
      environment: my-cluster:my-conda-env # <-- Nested env syntax
      script_path: scripts/run-sim.py
      inputs:
        - config/my-sim-config.yaml
      outputs:
        - results/all.h5
      slurm:
        options:
          - --time=60
    post-process-notebook:
      kind: jupyter-notebook
      notebook_path: notebooks/post-process.ipynb
      environment: my-cluster:my-conda-env
      inputs:
        - from_stage_outputs: sim
      slurm:
        options:
          - --gpus=1
```
