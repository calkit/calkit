# Storage

Calkit keeps the history of every file in your project.
By default,
small text files like code and LaTeX source go to the project's Git repo,
and everything else,
e.g., datasets, figures, and simulation results,
goes to the Calkit Hub (calkit.io).
You can also send some or all of those files somewhere else,
e.g., your lab's Hugging Face or S3 storage:

```sh
calkit add data/raw --to big-data
```

Either way,
you work with your files the same way,
and Calkit takes care of getting them where they need to go.
Under the hood, Calkit uses Git and DVC,
so `git` and `dvc` commands still work on the project if you need them.

## One login for everything

You only need to log in to Calkit once on each computer,
no matter where your files are stored.
Calkit handles access to your storage for you,
so there's nothing else to set up,
even on shared computers like HPC clusters.

This also means:

- Collaborators only need access to the project.
  They don't need accounts with your storage provider,
  and you never need to share passwords or keys with them.
- Your files go directly between your computer and your storage.
  They don't pass through calkit.io along the way.

## Connecting your own storage

Storage is connected to your account, not to a single project,
so you can connect it once and use it for any of your projects.
Every account starts with the Calkit Hub's built-in storage,
which is what projects use unless you choose otherwise.

To connect storage,
visit the storage section of your
[hub account settings](https://calkit.io/settings).
Organizations can also connect storage,
which is available to all projects owned by that organization.

To list the storage available to you:

```sh
calkit hub list storage
```

To use one of your connected storage options for a project's files
instead of the built-in storage:

```sh
calkit update storage --name dvc my-hf-bucket
```

which adds this to `calkit.yaml`:

```yaml
storage:
  dvc:
    kind: calkit # optional
    hub: calkit.io # optional
    name: my-hf-bucket
```

This can move a lot of data,
so read [Changing where files are stored](#changing-where-files-are-stored)
first.

Each project gets its own folder in your storage,
so you can use the same storage for many projects.

## Choosing storage per path

Not everything in a project needs to go to the same place.
For example,
you might want one big dataset on Hugging Face,
while figures stay on calkit.io.
To do this,
give the storage a name in `calkit.yaml`,
and use that name for the paths that should go there:

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

`git` and `dvc` are the names of the built-in storage,
so they can't be used for your own.
You can point `dvc` at your own storage, though, as shown above.

## Hugging Face

### Buckets

A [Hugging Face (HF) bucket](https://huggingface.co/docs/hub/en/storage-buckets)
is a simple place to keep large files,
with a free allowance and low-cost storage beyond that.
Usage is billed by HF and doesn't count against your Calkit plan.
There are two ways to connect one.

#### Option 1: Connecting your HF account

Visit your [hub account settings](https://calkit.io/settings)
and click the connect button next to Hugging Face.
Then add Hugging Face storage,
choosing your HF account or one of your HF organizations.
Calkit will create a private bucket named `calkit` there and manage it
for you.
It stays private,
even if some of the projects stored in it are public.

This is the easiest option,
but it does give Calkit access to everything in that HF account or
organization.
If you'd rather limit Calkit to a single bucket,
use Option 2.

#### Option 2: Connecting a single bucket

1. [Create a bucket](https://huggingface.co/new-bucket) under your HF
   account or organization, e.g., `my-username/calkit`.
2. [Create a fine-grained access token](https://huggingface.co/settings/tokens)
   with write access to only that bucket.
3. In the token's dropdown menu,
   choose "Generate S3 credentials."
4. Add S3 storage in your hub account settings,
   choose Hugging Face as the provider,
   and enter the bucket name and the credentials from step 3.

Calkit can then only ever touch that bucket,
and nothing else in your HF account.

### Datasets

HF Datasets are how many researchers share datasets,
with a page describing the dataset, a preview of the data, and search.
You can send a specific path in your project to an HF Dataset,
e.g., a dataset you want others to find and use.
Calkit keeps the files at the same paths they have in your project,
so it's easy to browse,
and keeps its history in step with your project's.

HF Datasets keep every version of every file,
so they're better suited to finished datasets than to everything a
project produces along the way.

## S3 storage

If your lab or institution already has storage that works with Amazon S3,
e.g., Amazon S3 itself, Cloudflare R2, Wasabi, or MinIO,
you can connect a bucket there with its address and an access key.
When you add it,
the hub checks that the key works,
and gives you instructions for creating one that can only access that
bucket, if needed.

## Changing where files are stored

You can change where files are stored at any time
by editing the `storage` section of `calkit.yaml`,
or the `storage` of a path.
Since that means moving files,
`calkit push` will first show you how many files and how much data will be
moved,
and ask you to confirm.
Only the project owner can do this,
since it uses their storage.

The move then happens on calkit.io, in the background,
so you don't need to download and re-upload anything,
and you can close your laptop.

- New files go to the new storage right away.
- Until the move is finished,
  Calkit will look in both places,
  so you and your collaborators can keep working the whole time.
- Nothing is deleted from the old storage when the move is done.
  You can delete those files yourself once you've checked everything made
  it over.

Moving a path into or out of the project's Git repo is different,
since it changes how the project's history is kept.
That happens on your computer the next time you commit.

## Forks

In Calkit, a project has a single home,
and collaborators work on it there,
rather than in copies of it.
A fork is a new project based on another one,
which will go its own way.

A fork's `calkit.yaml` starts out with the same storage names,
but they now refer to the new owner's account,
so the first `calkit push` will ask you to choose your own storage for
them.
Files from before the fork can still be downloaded from the original
project's storage,
as long as you have access to it.

## Using your storage without Calkit

Your files are always stored in a standard layout that DVC understands,
so you're never locked in to Calkit.
If you ever want to download them without Calkit,
you can do so with DVC directly,
using your own login for that storage:

```sh
dvc pull -r hf
```

## Public archival

For public archival access, create a [release](releases.md)
to a service that mints DOIs for artifacts.
These integrate nicely with the Calkit CLI,
so clones of the project will automatically download from these services
to hydrate the DVC cache and make checking them out seamless.

## On the roadmap

- Google Drive
- OneDrive
- Box
- Connecting AWS without creating access keys
- Releasing to HF Datasets
- Keeping the project's Git repo on GitLab, Codeberg, HF, or calkit.io
  ([#1254](https://github.com/calkit/calkit/issues/1254))

## Design notes

This section is for the design phase and will be removed.

- Audience: scientists who want their files' history kept,
  not software developers or infrastructure specialists.
  The user-facing docs above say where files go and what it costs,
  and leave out tracking mechanisms, protocols, and hashes.
  Those details belong here and in developer docs.
- Moved out of the user-facing docs:
  every project's DVC remote is `ck://{owner}/{project}`;
  the hub hands out short-lived URLs so bytes skip the hub;
  the hub acts as the project's Git LFS server via `.lfsconfig`;
  `dvc-zip` and `git-lfs` are also built-in, configurable names,
  and `git-lfs` stays an advanced, mostly undocumented option;
  a storage entry can take `hub: {domain}` for storage on another hub;
  the no-hub fallback remote in `.dvc/config` is S3 over HF's gateway,
  with credentials from `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
  or `dvc remote modify --local`;
  HF Datasets mirroring uses the MD5 index described below;
  git-annex support through a Calkit special remote;
  and AWS role assumption.
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
  That's what makes it fine for storage names to travel with the repo:
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
- Users pick storage, not a tracking mechanism,
  and Calkit picks the mechanism from the storage kind.
  `git`, `dvc`, `dvc-zip`, and `git-lfs` are built-in storage instances,
  and a user-defined entry gets its mechanism from its resource,
  e.g., a bucket, or HF Datasets through the MD5 index, means DVC.
  `calkit add --to` grows from `git`, `dvc`, and `dvc-zip` to any storage
  name.
  Internally, not every mechanism works with every storage kind:

  | Content          | Git | S3, HF bucket, Drive, OneDrive, Box | HF Datasets           |
  | ---------------- | --- | ----------------------------------- | --------------------- |
  | Git-tracked      | Yes | No                                  | Yes (whole repo)      |
  | DVC              | No  | Yes                                 | Yes (MD5 index)       |
  | Git LFS          | No  | Yes                                 | Yes (natively)        |
  | Issues (git-bug) | Yes | Not practically                     | Unknown (custom refs) |

  Where a storage kind supports more than one,
  e.g., a bucket can hold DVC or LFS objects,
  Calkit picks the default (DVC),
  and the built-in `git-lfs` is the way to get the other.
  The schema shouldn't assume every storage entry holds DVC files,
  and the hub should reject pairs that don't work.

- Issues are a future content type,
  not a storage kind
  ([#654](https://github.com/calkit/calkit/issues/654),
  [#736](https://github.com/calkit/calkit/issues/736)).
  git-bug stores them as Git objects under `refs/bugs/*` and
  `refs/identities/*`,
  outside every branch,
  and syncs with plain Git push and pull,
  so they need Git-kind storage,
  though not necessarily the same remote as the code.
  Issue trackers like GitHub Issues are mirrors, not storage,
  kept in sync by the hub running git-bug's bridges,
  the same way HF Datasets and Zenodo releases are published copies.
  This depends on Git storage
  ([#1254](https://github.com/calkit/calkit/issues/1254)),
  since pushing issues through the hub is a Git push.
  Other open items:
  the hub is Python and git-bug is Go,
  so it would call the binary or implement the spec;
  check which Git hosts keep custom refs;
  and git-bug has no boards,
  so Kanban columns would be labels or a Calkit extension.
- Commands name the segment they configure,
  i.e., `dvc-storage` and `lfs-storage`,
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
- Git storage is out of scope for this PR,
  and stays as `git_repo_url` on the hub.
  The Git URL shouldn't go in `calkit.yaml`:
  a commit changing it is pushed to the old remote,
  other clones keep the old `origin`,
  the history has to be mirrored with credentials for both hosts,
  and anyone with push access could repoint the project the hub acts on.
  Changing it should be an owner-only action on the hub.
  Later, Git hosts could be storage resources with `kind: git`,
  under [#1254](https://github.com/calkit/calkit/issues/1254),
  which brings its own auth layer:
  per-host tokens, pushes from collaborators,
  and maybe the hub proxying Git traffic for hosts that can't issue
  tokens scoped to one repo.
  GitHub App installation tokens can be;
  it's not clear HF can do better than the user's whole OAuth token.
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
