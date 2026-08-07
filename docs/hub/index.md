# Calkit hubs

A Calkit hub is where Calkit projects are shared, backed up,
and collaborated on.
It serves as a project management interface and a DVC remote for easily
storing all versions of your data/code/figures/publications, interacting
with your collaborators, reusing others' research artifacts, etc.
The main hub is [calkit.io](https://calkit.io).

A hub is optional: projects are fully functional offline, and the Git repo
remains the source of truth.

To authenticate the CLI, execute:

```sh
calkit hub login
```

Note this will need to be done once per machine, e.g., once on your
personal laptop and once on an HPC cluster.

By default the CLI talks to calkit.io.
To target a different hub by default, e.g., one run by your lab, set:

```sh
calkit config set default_hub https://your-hub.example.edu
```

Commands that take a `--hub` option, like `calkit new project`, can also
target an instance one-off, e.g., `--hub staging.calkit.io`.

Like the rest of Calkit, the hub is free and open source, so
[you can run your own](self-hosting.md).

## Using DVC remotes other than a Calkit hub

It's possible to configure DVC to use a different remote storage location,
e.g., an AWS S3 bucket.
However,
any artifacts stored externally will not be viewable on the hub,
and permissions for these locations will need to be configured
for each collaborator manually.
