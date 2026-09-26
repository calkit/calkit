# Storage

Calkit projects keep their files in two places:
Git for text and other small files,
and DVC for large and/or binary files, e.g.,
imported datasets or pipeline outputs.
Git can push to any remote, though GitHub is the default.
DVC can also push to any compatible remote,
but by default Calkit uses the Calkit Hub (calkit.io).

This page is mostly about the DVC side,
i.e., where your large files actually live,
and how you can choose that for yourself.

## The hub handles storage auth

The idea is that you should only need to authenticate once per machine,
with Calkit,
no matter where your files live.
DVC can talk directly to S3 and many other backends,
but every one of those is another account to set up on every machine,
and every collaborator needs access to each of them too.
That adds up quickly,
especially on shared machines like HPC clusters.

So instead, every Calkit project uses the same DVC remote,
which looks like `ck://{owner}/{project}`.
When DVC needs to read or write a file,
Calkit asks the hub where that file should go,
and the hub responds with a short-lived URL for the storage backend
configured for that project.
The file is then transferred directly between your machine and that
backend.
It never passes through the hub.

This means:

- Your collaborators only need access to the project on the hub.
  They don't need accounts on your storage provider,
  and you don't need to share any credentials with them.
- Your storage credentials live in your hub account,
  not in your project repo or on every machine.
- You can change where a project's files are stored without
  changing anything in the project itself.

## Storage resources

Storage is set up at the account level, not the project level.
You connect a storage resource to your account,
e.g., a Hugging Face bucket,
then assign it to any of your projects.
Every account starts with Calkit Cloud storage,
which is what projects use unless you choose otherwise.

To add a storage resource,
visit the storage section of your
[hub account settings](https://calkit.io/settings).
Organizations can also have storage resources,
which are available to all projects owned by that organization.

To assign a storage resource to a project,
use the project's settings page on the hub,
or from the CLI:

```sh
calkit storage set my-hf-bucket
```

To see where a project's files are stored:

```sh
calkit storage show
```

Each project gets its own folder inside a storage resource,
named like `{owner}/{project}`,
so one resource can hold many projects.

## Hugging Face

Calkit can use a
[Hugging Face (HF) Storage Bucket](https://huggingface.co/docs/hub/en/storage-buckets)
as a storage resource.
Buckets are fast, mutable object storage with chunk-level deduplication,
which makes them a good fit for DVC,
since Git is already handling the versioning.

To connect one:

1. [Create a bucket](https://huggingface.co/new-bucket) under your HF
   account or organization, e.g., `my-username/calkit`.
   It can be private,
   even if some of the projects stored in it are public.
2. [Create a fine-grained access token](https://huggingface.co/settings/tokens)
   with write access to only that bucket.
3. In the token's dropdown menu,
   choose "Generate S3 credentials."
4. Add a Hugging Face storage resource in your hub account settings
   with the bucket name and the S3 credentials.

Scoping the token to one bucket means Calkit can only ever touch that
bucket,
and nothing else in your HF account.
Usage is billed by HF and doesn't count against your Calkit plan.

HF also has Datasets repos,
which are better suited to publishing finished artifacts than to storing
everything a project produces.
Publishing to Datasets repos is on the roadmap as another kind of
[release](releases.md).

## Changing a project's storage

A project's storage can be changed at any time.
Files already pushed stay where they are,
and are copied to the new storage in the background.
Until that copy is finished,
the hub will look in both places,
so reads keep working the whole time.
Since DVC files are addressed by their content,
there's no risk of getting a stale version during the copy.

## Using your storage without the hub

Calkit is designed to avoid lock-in,
so your files are always stored in the same layout DVC uses for its own
remotes.
When a project is assigned to a storage resource,
Calkit also adds a second, non-default remote to `.dvc/config` that points
directly at it.
If you ever want to go around the hub,
you can pull with plain DVC,
using your own credentials for that provider:

```sh
dvc pull -r hf
```

For HF buckets, this uses DVC's S3 support
through HF's [S3-compatible gateway](https://huggingface.co/docs/hub/storage-buckets-s3).
Credentials can be set with the `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY` environmental variables,
or with `dvc remote modify --local` so they stay out of Git.

## Public archival

For public archival access, create a [release](releases.md)
to a service that mints DOIs for artifacts.
These integrate nicely with the Calkit CLI,
so clones of the project will automatically download from these services
to hydrate the DVC cache and make checking them out seamless.

## On the roadmap

- Amazon S3 and other S3-compatible storage
- OneDrive
- Box
- Google Drive
- Releasing to HF Datasets repos
- Handling Git remote auth the same way,
  so GitHub credentials don't need to be set up on every machine

## Design notes

This section is for the design phase and will be removed.

- The hub owns the storage abstraction:
  credentials, which resource a project uses, and migrations.
  None of this goes in `calkit.yaml`.
  The one thing that does go in the repo is the direct remote in
  `.dvc/config`,
  so the project isn't locked into the hub.
- The hub writes objects under `{owner}/{project}/files/md5/...`,
  i.e., the DVC layout,
  so the direct remote and the hub see the same files.
- One resource per account rather than one bucket per project,
  because creating buckets on the fly would need a token that can write to
  the user's whole HF namespace.
- For HF, the hub signs S3 URLs itself with the stored credentials.
  Signing is local, so there's no HF API call per file,
  and the client's existing `presigned-url` and `presigned-multipart`
  access kinds may work unchanged.
- To verify:
  does `s3.hf.co` accept presigned query-string URLs,
  including for multipart parts?
  If not, the fallback is a new access kind using short-lived Xet tokens
  and the `hf_xet` client,
  which would also get us chunk-level transfer deduplication
  (see [#675](https://github.com/calkit/calkit/issues/675)).
- To verify:
  can S3 credentials be created programmatically,
  e.g., through HF OAuth,
  to avoid the copy-paste step?
  OAuth token exchange appears to be Enterprise-only.
- Public projects in private buckets are fine,
  since the hub signs read URLs for anyone who can see the project.
- Related issues:
  [#791](https://github.com/calkit/calkit/issues/791),
  [#1253](https://github.com/calkit/calkit/issues/1253),
  [#675](https://github.com/calkit/calkit/issues/675),
  [#394](https://github.com/calkit/calkit/issues/394).
