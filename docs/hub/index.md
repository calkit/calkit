# The Calkit hub

A hub is where Calkit projects are shared, backed up, and collaborated on.
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

Like the rest of Calkit, the hub is free and open source, so
[you can host your own](https://github.com/calkit/calkit/tree/main/hub).

## Using DVC remotes other than the hub

It's possible to configure DVC to use a different remote storage location,
e.g., an AWS S3 bucket.
However,
any artifacts stored externally will not be viewable on the hub,
and permissions for these locations will need to be configured
for each collaborator manually.
