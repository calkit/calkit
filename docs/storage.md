# Storage

Calkit separates two questions about every file in a project:

1. **How is it tracked?**
   Git for text and other small files, e.g., code and LaTeX source,
   and DVC for large and/or binary files, e.g.,
   imported datasets and pipeline outputs.
   Git LFS is also supported,
   and git-annex is on the roadmap.
2. **Where is it stored?**
   By default, Git files go to GitHub
   and everything else goes to the Calkit Hub (calkit.io),
   but you can connect your own storage,
   e.g., a Hugging Face bucket or an S3 bucket.

Both are declared in your project's `calkit.yaml`,
so they go wherever the project goes.
But `calkit.yaml` only ever refers to storage by name.
The storage itself,
along with any credentials needed to use it,
is set up in your account on the hub,
so credentials never need to be in your project or on every machine.

## The hub handles storage auth

The idea is that you should only need to authenticate once per machine,
with Calkit,
no matter where your files live.
DVC, Git LFS, and git-annex can all talk directly to S3 and many other
backends,
but every one of those is another account to set up on every machine,
and every collaborator needs access to each of them too.
That adds up quickly,
especially on shared machines like HPC clusters.

So instead, the hub sits in front of your storage for every tracking
mechanism:

- **DVC:** Every Calkit project uses a DVC remote that looks like
  `ck://{owner}/{project}`.
- **Git LFS:** The hub acts as the project's LFS server,
  set in the project's `.lfsconfig`.
- **Git:** Calkit acts as a Git credential helper,
  getting short-lived credentials for the project's Git remote from the
  hub.

When a file needs to be read or written,
Calkit asks the hub where it should go,
and the hub responds with a short-lived URL or credential for the storage
behind that project.
The file is then transferred directly between your machine and the
storage.
It never passes through the hub.

This means:

- Your collaborators only need access to the project on the hub.
  They don't need accounts on your storage provider,
  and you don't need to share any credentials with them.
- Your storage credentials live in your hub account,
  not in your project repo or on every machine.
- You can change where a project's files are stored without
  changing the project's remotes.

## Storage resources

Storage is set up at the account level, not the project level.
You connect a storage resource to your account,
e.g., a Hugging Face bucket,
then refer to it by name from any of your projects.
Every account starts with Calkit Cloud storage,
which is what projects use unless you choose otherwise.

To add a storage resource,
visit the storage section of your
[hub account settings](https://calkit.io/settings).
Organizations can also have storage resources,
which are available to all projects owned by that organization.

To list the storage resources available to you:

```sh
calkit hub list storage
```

A project's DVC files are stored in the Calkit Hub's internal
storage by default.
To use one of your attached external storage resources instead:

```sh
calkit update storage --name dvc my-hf-bucket
```

which adds this to `calkit.yaml`:

```yaml
storage:
  dvc:
    name: my-hf-bucket
```

This can move a lot of data,
so read [Changing where files are stored](#changing-where-files-are-stored)
first.

Names always refer to storage resources in the project owner's account,
on the project's hub.
If the storage resource is on a different hub,
add `hub: {domain}`.

Each project gets its own folder inside a storage resource,
named like `{owner}/{project}`,
so one resource can hold many projects.

## Choosing storage per path

Not everything in a project needs to go to the same place.
For example,
you might want one big dataset in a Hugging Face bucket,
while figures stay on calkit.io.
To do this,
add your own entry to the `storage` section of `calkit.yaml`,
and use its name wherever you'd normally write `git` or `dvc`:

```yaml
storage:
  big-data:
    name: my-hf-bucket

datasets:
  - path: data/raw
    storage: big-data

pipeline:
  stages:
    run-sim:
      kind: python-script
      script_path: scripts/run_sim.py
      outputs:
        - path: results
          storage: big-data
```

Files with `storage: big-data` are then stored in `my-hf-bucket`.
How they're tracked follows from the kind of storage,
e.g., a bucket is used like any other DVC storage,
so there's nothing else to set.

`git`, `dvc`, `dvc-zip`, and `git-lfs` are the built-in storage names,
so they're reserved,
but they can be configured,
e.g., `dvc` above,
to change where they store files.

## Git storage

A project's Git remote can also be declared in `calkit.yaml`:

```yaml
storage:
  git:
    url: https://github.com/my-org/my-project
```

Calkit keeps the project's `origin` remote in sync with this,
so it goes with the project,
and anyone who clones it pushes to the same place.
Authentication still goes through the hub,
so collaborators don't need to set up GitHub credentials on each
machine.

## Hugging Face

### Buckets

Calkit can use a
[Hugging Face (HF) Storage Bucket](https://huggingface.co/docs/hub/en/storage-buckets)
as a storage resource for DVC and Git LFS.
Buckets are fast, mutable object storage with chunk-level deduplication,
which makes them a good fit,
since Git is already handling the versioning.
Usage is billed by HF and doesn't count against your Calkit plan.
There are two ways to set one up.

#### Option 1: Connecting your HF account

Visit your [hub account settings](https://calkit.io/settings)
and click the connect button next to Hugging Face.
Then add a Hugging Face storage resource,
choosing your HF account or one of your HF organizations as the owner.
Calkit will create a private bucket named `calkit` there and manage it
for you.
It can stay private,
even if some of the projects stored in it are public.

This is the easiest option,
but it does give Calkit access to everything in that HF account or
organization.
If you'd rather limit Calkit to a single bucket,
use Option 2.

#### Option 2: Using S3 credentials for one bucket

HF buckets can also be accessed through their
[S3-compatible API](https://huggingface.co/docs/hub/storage-buckets-s3),
so they can be connected like any other
[S3 bucket](#amazon-s3-and-s3-compatible-storage).

1. [Create a bucket](https://huggingface.co/new-bucket) under your HF
   account or organization, e.g., `my-username/calkit`.
2. [Create a fine-grained access token](https://huggingface.co/settings/tokens)
   with write access to only that bucket.
3. In the token's dropdown menu,
   choose "Generate S3 credentials."
4. Add an S3 storage resource in your hub account settings,
   choosing Hugging Face as the provider,
   and enter the bucket name and the S3 credentials.

Since the token is scoped to one bucket,
Calkit can only ever touch that bucket,
and nothing else in your HF account.

### Datasets

HF Datasets repos are Git repos,
with large files stored using LFS (backed by Xet).
Unlike a bucket,
files in a Datasets repo are stored at their actual paths,
so the repo can be browsed like your project,
and gets a dataset card, a data viewer, and HF's search.

With your HF account connected,
a Datasets repo can be used as DVC storage,
either as a project's default or for
[specific paths](#choosing-storage-per-path),
e.g., just the dataset you want others to find.
When you `calkit push`,
Calkit uploads files to the repo at the same paths they have in your
project,
and makes one commit on HF for each commit it's mirroring.
The hub keeps track of which HF revision and path holds each version of
each file,
so DVC can still find them by their MD5 checksum.

A Datasets repo can also be used as a project's Git storage,
so the whole project,
large files included,
lives on HF.

Datasets repos keep every version of every file,
so they're better suited to finished artifacts than to everything a
project produces along the way.
Publishing to a Datasets repo is also on the roadmap as another kind of
[release](releases.md).

## Amazon S3 and S3-compatible storage

Any S3-compatible bucket can be used as a storage resource,
e.g., on Amazon S3, Cloudflare R2, Wasabi, MinIO,
or storage run by your institution.
An S3 storage resource is a bucket URI,
an endpoint (if not using AWS),
and an access key for that bucket.

We recommend creating credentials that can only access that one bucket,
e.g., an IAM user with a policy limited to it.
The hub provides a policy you can copy when adding the resource.
When you add it,
the hub checks that the credentials can read and write the bucket,
and will warn you if they have more access than they need.

## Git LFS

Outputs and datasets can use `storage: git-lfs`,
which keeps a small pointer file in Git and the file itself in LFS
storage.
This can be convenient for files that change rarely,
since they come along with a plain `git clone`,
with no DVC needed.

LFS files go to the same kinds of storage resources as DVC files,
with the hub acting as the LFS server,
so the project's Git host doesn't need to support LFS,
and you don't pay for LFS storage there.

## Changing where files are stored

Where files are stored can be changed at any time,
by editing the `storage` section of `calkit.yaml`,
or the `storage` of a path,
but since that means moving files,
`calkit push` will first show you how many files and how much data will be
moved,
and ask you to confirm.
Only the project owner can do this,
since it uses their storage.

The move then happens on the hub, in the background,
similar to how Kubernetes applies a manifest,
so you don't need to download and re-upload anything,
and you can close your laptop.

- New pushes go to the new storage right away.
- Until the move is finished,
  the hub will look in both places,
  so pulls keep working the whole time.
- Since files are addressed by their content,
  there's no risk of getting a stale version during the move.
- Files are not deleted from the old storage once the move is done.
  You can delete them yourself after checking everything made it over.

Changing how a path is tracked,
e.g., from `dvc` to `git-lfs`,
is different,
since it changes the project's history going forward.
That happens on your machine the next time you commit.

## Forks

In Calkit, a project has a single home,
and collaborators work on it there,
rather than in forks of it.
A fork is a new project derived from another one,
which will go its own way.

A fork's `calkit.yaml` starts out with the same storage names,
but they now refer to the new owner's account,
so the first `calkit push` will ask you to point them at your own
storage resources,
and set a new Git remote.
Files from before the fork can still be pulled from the original
project's storage,
as long as you have access to it.

## Using your storage without the hub

Calkit is designed to avoid lock-in,
so your files are always stored in the same layout DVC and Git LFS use
for their own remotes.
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

- git-annex, through a Calkit special remote
- Connecting an AWS account with a role Calkit can assume,
  so no long-lived keys are stored
- OneDrive
- Box
- Google Drive
- Releasing to HF Datasets repos
- Git storage on GitLab, Codeberg, HF, or the hub itself

## Design notes

This section is for the design phase and will be removed.

- The split between the repo and the hub:
  `calkit.yaml` says how each path is tracked and which storage it uses,
  by name.
  The hub resolves each name to a resource in the project owner's
  account,
  holds its credentials,
  and runs moves.
  No magic matching:
  a name that doesn't resolve is an error on push,
  never a silent fallback that starts a move.
- A project has a single home,
  and forks diverge rather than converge.
  That's what makes it fine for storage names and the Git URL to travel
  with the repo:
  collaborators share the owner's resources through the hub,
  and a fork is a deliberate break where remapping is expected.
  Fork reads fall back to the parent project's storage.
- The repo also gets a direct remote in `.dvc/config` for each storage
  entry,
  so the project isn't locked into the hub.
- Account storage resources are managed imperatively,
  through the web UI and API,
  not declaratively from a file like `~/.calkit/storage.yaml`.
  They involve secrets and change rarely,
  so a reconcile loop isn't worth it there.
- Calkit already compiles `calkit.yaml` into `dvc.yaml`,
  so each storage entry becomes its own `ck` remote,
  e.g., `ck://{owner}/{project}?storage=big-data`,
  and outputs get a per-output `remote` pointing at it.
  `.dvc` files for datasets get the same.
  This is plain DVC,
  so even a plain `dvc push` sends files to the right place.
- On the hub, the `storage` query parameter is looked up in the pushed
  `calkit.yaml` to find the resource.
  The hub keeps a record of every resource a project has used,
  and reads fall back across all of them,
  which is what makes moving files lazily safe.
- `calkit push` is where storage changes are confirmed,
  since it can compare the local `calkit.yaml` with what the hub last
  saw.
  The hub's reconcile loop runs after the Git push,
  triggered by `calkit push` notifying the hub,
  or by a webhook from the Git host.
  Nothing needs to move before the next push works,
  so a move can be slow, retried, or skipped.
- The optional `hub` key is for federation
  ([#1252](https://github.com/calkit/calkit/issues/1252)).
  It means another login,
  so it should be rare.
- Entries don't declare a tracking mechanism.
  `git`, `dvc`, `dvc-zip`, and `git-lfs` are built-in storage instances,
  and a user-defined entry gets its mechanism from its resource:
  object storage like a bucket, and HF Datasets through the MD5 index,
  are DVC,
  and a Git URL is Git.
  Open question:
  can a user-defined entry be LFS,
  e.g., LFS objects in an HF bucket,
  or does LFS only ever go through the built-in `git-lfs`,
  configured with `git-lfs: {name: ...}`?
- Commands name the segment they configure,
  i.e., `dvc-storage`, `lfs-storage`, and `git-storage`,
  and each edits the matching reserved entry in `calkit.yaml`.
- The hub writes DVC objects under `{owner}/{project}/files/md5/...`
  and LFS objects under `{owner}/{project}/lfs/objects/...`,
  i.e., the layouts DVC and LFS use themselves,
  so a direct remote and the hub see the same files.
- HF Datasets as DVC storage needs a translation layer,
  since DVC pushes and pulls by MD5,
  while the repo stores files by path,
  with Git history as the versioning.
  The hub keeps an index of MD5 to (HF revision, path, LFS OID).
  Reads resolve through it to
  `datasets/{repo}/resolve/{rev}/{path}`;
  for private repos the hub makes that request itself and returns the
  302's CDN URL,
  like the Box trick in #1253.
- The `ck` remote still only sees content hashes,
  so HF Datasets needs an MD5-to-path map at push time.
  `calkit push` can send it from the local `dvc.lock` and `.dvc` files,
  and the client uploads straight to the Datasets repo with a short-lived
  Xet write token from the hub,
  and the hub makes the HF commit once the push is done.
  With a plain `dvc push`,
  files are staged in the project's default storage,
  and the reconcile loop copies them into the Datasets repo after the Git
  push,
  which means uploading the bytes again,
  since server-side copy from a bucket into a repo isn't available yet
  (it's on HF's roadmap).
- Directory outputs are `.dir` manifests in DVC.
  The hub can synthesize those from the index,
  or store them in the HF repo under a hidden path.
- The index should be possible to rebuild from HF alone,
  to avoid lock-in:
  commit the project's `dvc.lock` and `.dvc` files into the HF repo too,
  and put the project commit SHA in each HF commit message.
  Then any HF revision says which MD5 lives at which path.
- History rewrites on the HF side,
  e.g., squashing to reclaim space,
  break the index.
  The hub should detect that (the revision disappears) and re-upload or
  mark the objects missing.
- Check HF's rate limits on commits,
  since this is one commit per mirrored project commit,
  or batch them per push.
- The hub as an LFS server is a small surface:
  the LFS batch API already returns an `href` and headers for each
  object,
  so it can return the same presigned URLs as `fs/ops`,
  and stock `git-lfs` needs no custom transfer agent.
  Auth is a Git credential helper for the hub's host.
- git-annex would use its external special remote protocol,
  with a small `git-annex-remote-calkit` asking the hub for URLs.
- Two layers of storage resource kinds.
  `s3` is the low-level one:
  a bucket URI, an optional endpoint, and credentials.
  HF buckets connected with S3 credentials are just `s3` with a preset
  endpoint.
  `hf-bucket` is the managed one,
  where the user connects their HF account with OAuth and the hub creates
  and manages the bucket.
  Other managed kinds, e.g., OneDrive and Box,
  would follow the `hf-bucket` pattern.
- The trade-off between the two is convenience vs. scope.
  An HF OAuth token spans the whole namespace,
  while S3 credentials can be limited to one bucket.
- One resource per account rather than one bucket per project,
  so the credentials never need to create buckets on the fly.
- For `s3`, the hub signs URLs itself with the stored credentials.
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
  how does `hf-bucket` move bytes?
  S3 credentials appear to only be created in the HF UI,
  so an OAuth token probably can't be used with the S3 gateway.
  The likely path is the hub requesting short-lived Xet tokens for the
  bucket with the user's OAuth token,
  which would need the Xet access kind above.
  Check which OAuth scopes are needed to create buckets.
- To verify:
  routing Git auth through the hub needs short-lived credentials scoped to
  one repo.
  GitHub App installation tokens can be scoped to a single repo and set of
  permissions, so GitHub works.
  For HF Datasets repos,
  it's not clear the hub can mint anything narrower than the user's OAuth
  token,
  which must never be handed to collaborators.
  If not, HF Git storage may need the hub to proxy Git traffic,
  or only work for the owner.
- Later, AWS role assumption as a second auth method for `s3`,
  ideally with the hub acting as an OIDC identity provider so it doesn't
  need its own AWS account.
  The same approach would work for GCP and Azure.
- Public projects in private buckets are fine,
  since the hub signs read URLs for anyone who can see the project.
- Related issues:
  [#791](https://github.com/calkit/calkit/issues/791),
  [#1253](https://github.com/calkit/calkit/issues/1253),
  [#675](https://github.com/calkit/calkit/issues/675),
  [#394](https://github.com/calkit/calkit/issues/394).
