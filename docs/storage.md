# Storage

By default, Calkit has two kinds of storage for project files: Git and DVC.
Git can be configured to push to any remote, though
GitHub is the default.
DVC similarly can be set up to push to any compatible remote,
but Calkit integrated with a Calkit Hub (calkit.io) by default.
It is possible to configure storage in a more fine-grained way,
however, both from the CLI and by connecting some to the Hub,
allowing it to act as an authenticator/authorizer,
but letting you fully control the backend where the files live.

This mostly concerns large and/or binary files in the project, e.g.,
large imported datasets or pipeline outputs.

Routing storage through a Calkit Hub has the advantage of not requiring
your collaborators to have accounts on every back end service,
and for you to share it with them there explicitly.

## Hugging Face

Calkit can use Hugging Face (HF) as a storage mechanism, using either their
Datasets or Buckets service.
To configure a project to use HF, add this to `calkit.yaml`:

```yaml
storage:
  dvc:
    kind: hf-datasets
```

Calkit will then use...

## Public archival

For public archival access, create a [release](releases.md)
to a service that mints DOIs for artifacts.
These integrate nicely with the Calkit CLI,
so clones of the project will automatically download from these services
to hydrate the DVC cache and make checking them out seamless.

## On the roadmap

- Use Google Drive for storage
- OneDrive
- Dropbox
- Box
