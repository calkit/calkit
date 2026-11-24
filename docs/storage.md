# Storage

Calkit keeps the history of every file in your project.
By default,
small text files like code and LaTeX source go to the project's Git repo,
and everything else,
e.g., datasets, figures, and simulation results,
goes to the Calkit Hub (calkit.io).

<!-- TODO: needs human review -->

Those larger files can also go somewhere else,
e.g., a Hugging Face bucket.

<!-- TODO: needs human review -->

Either way,
you work with your files the same,
and Calkit gets them where they need to go.
Calkit uses Git and DVC under the hood,
so `git` and `dvc` commands still work if you need them,
but to send and get files,
use `calkit push` and `calkit pull`,
since they reach everywhere the project's files are stored.

## One login for everything

You only need to log in to Calkit once on each machine,
no matter where your files are stored.
Calkit handles access to your storage,
so there's nothing else to set up,
even on shared machines like HPC clusters.

This also means:

- Collaborators only need access to the project.
  They don't need accounts with your storage provider,
  and you never need to share passwords or keys with them.
- Your files go directly between your machine and your storage,
  without passing through calkit.io.

## Connecting your own storage

<!-- TODO: needs human review -->

Every account starts with Calkit Hub storage,
which projects use by default.
To use your own:

1. Connect the service under connected accounts in your
   [hub account settings](https://calkit.io/settings).
2. In the project's settings on the hub,
   select where its large files should go,
   or create a new Hugging Face bucket.

To see where a project's files are stored
and how much Calkit Hub storage it's using,
run this from the project:

```sh
calkit describe storage
```

Changing a project's storage only affects files pushed after the change
(see [Changing where files are stored](#changing-where-files-are-stored)).

## Hugging Face

A [Hugging Face (HF) bucket](https://huggingface.co/docs/hub/en/storage-buckets)
is a simple place to keep large files,
with a free allowance and low-cost storage beyond that.
Usage is billed by HF and doesn't count against your Calkit plan.
When part of a large file changes,
only that part gets uploaded.

<!-- TODO: needs human review -->

To create one,
go to the project's settings on the hub and click "New Hugging Face bucket,"
connecting your HF account if asked.
Select your HF account or one of your HF organizations,
and Calkit will create a bucket there named after the project
and manage it for you.
If that name is taken, enter a different one.

A project's bucket has the same visibility as the project,
so making a project public also makes files from its earlier versions
public.
To keep those private,
keep the project private and publish a [release](releases.md) instead.
Removing old files from a bucket isn't supported yet.

If you disconnect your HF account while projects are storing files with it,
you'll need to choose whether to transfer those files to Calkit Hub storage,
delete them,
or leave them on HF, where those projects can no longer reach them.
To switch to a different HF account,
disconnect the current one first.

Connecting your HF account gives Calkit access to everything in that HF
account or organization.

### Already using DVC?

<!-- TODO: needs human review -->

DVC has no Hugging Face remote of its own,
but a DVC project can use one through Calkit:

1. [Install Calkit](installation.md) and log in with `calkit hub login`.
2. In the project, run `calkit init`,
   which keeps your existing Git and DVC setup.
3. Run `calkit update hub`
   to add the project to the Calkit Hub with its existing Git repo
   and make the hub its DVC remote.
   Any remote you already had stays configured.
4. In the project's settings on the hub,
   click "New Hugging Face bucket."
5. Run `calkit push` to send the files on this machine to the bucket.
   If some are only on your old remote,
   run `dvc pull -r {old remote}` first.

From then on, use `calkit push` and `calkit pull`.
A separately installed `dvc` can't reach the hub,
so `dvc push` and `dvc pull` may not work.

## Changing where files are stored

<!-- TODO: needs human review -->

Only the project owner can change where its files are stored,
since it uses their storage.
New files go to the new storage right away,
and existing files stay where they are.
Calkit still finds them there,
so you and your collaborators don't need to do anything.

When deleting a project,
you can choose to delete its files from storage too.
A bucket in someone else's Hugging Face account stays there.

## Using your storage without Calkit

<!-- TODO: needs human review -->

Your files are always stored in a standard layout that DVC understands,
so you're never locked in to Calkit.
To get them without Calkit,
download them into the project's DVC cache
with the storage service's own tools and your own login.

## Public archival

For public archival access, create a [release](releases.md)
to a service that mints DOIs for artifacts.
These integrate nicely with the Calkit CLI,
so clones of the project will automatically download from these services
to hydrate the DVC cache and make checking them out seamless.

## On the roadmap

<!-- TODO: needs human review -->

- Google Drive
- OneDrive
- Box
- S3 and storage that works with it,
  e.g., Amazon S3, Cloudflare R2, Wasabi, or MinIO
- Connecting AWS without creating access keys
- Connecting an existing HF bucket to a project with a token limited to it
- Choosing storage per path, e.g., one dataset on HF and the rest on
  calkit.io, in `calkit.yaml`
- Moving files to new storage when a project's storage changes
- Removing files a project no longer uses from its storage
- Choosing storage for a fork
- Releasing to HF Datasets
- Keeping the project's Git repo on GitLab, Codeberg, HF, or calkit.io
  ([#1254](https://github.com/calkit/calkit/issues/1254))
