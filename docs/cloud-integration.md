# Cloud integration

The Calkit Cloud ([calkit.io](https://calkit.io)) serves as a project
management interface and a DVC remote for easily storing all versions of your
data/code/figures/publications, interacting with your collaborators,
reusing others' research artifacts, etc.

To authenticate the CLI, execute:

```sh
calkit cloud login
```

Note this will need to be done once per machine, e.g., once on your
personal laptop and once on an HPC cluster.

Like the rest of Calkit, the Cloud platform is free and open source,
so [you can host your own](https://github.com/calkit/calkit-cloud).

## Using DVC remotes other than calkit.io

It's possible to configure DVC to use a different remote storage location,
e.g., an AWS S3 bucket.
However,
any artifacts stored externally will not be viewable on calkit.io,
and permissions for these locations will need to be configured
for each collaborator manually.
