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

If you already use Git LFS on GitHub,
`storage: git-lfs` works too,
and stores those files with GitHub's LFS.
If Git LFS isn't set up on your computer yet,
Calkit will offer to set it up for you.
Keep in mind that GitHub limits how much LFS storage and download
bandwidth you get,
and removing LFS files from GitHub later means deleting the repo or
contacting GitHub support.

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
The trade-off is speed:
with Option 1,
changing part of a large file only uploads the part that changed,
while with Option 2,
the whole file is uploaded again.

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
  `dvc-zip` and `git-lfs` are also built-in, configurable names;
  a storage entry can take `hub: {domain}` for storage on another hub;
  the no-hub fallback remote in `.dvc/config` is S3 over HF's gateway,
  with credentials from `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
  or `dvc remote modify --local`;
  HF Datasets mirroring uses the MD5 index described below;
  git-annex support through a Calkit special remote;
  and AWS role assumption.
- The split between the repo and the hub:
  `calkit.yaml` says which storage each path uses, by name.
  The hub resolves each name to a resource in the project owner's
  account,
  holds its credentials,
  and runs moves.
  No magic matching:
  names map to resources only by explicit,
  owner-approved choices.
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
- The hub keeps its own copy of each project's name-to-resource mapping,
  rather than reading it out of whatever `calkit.yaml` was last pushed.
  Two reasons.
  Timing: DVC usually pushes before Git,
  so the hub may not have seen a new name yet.
  Security: only the owner should change where files go,
  but anyone with push access can commit a `calkit.yaml` change,
  and the hub can't reliably tell who made a commit.
- So `calkit push` sends the local `storage` section to the hub before
  pushing anything.
  If it differs from the hub's mapping and the pusher is the owner,
  `calkit push` shows the move and asks to confirm,
  and the hub applies it.
  If the pusher isn't the owner,
  the hub records it as a pending change for the owner to approve on the
  project's settings page,
  and `calkit push` says so.
  Until then, the old mapping stays in effect,
  and names the hub doesn't know yet go to the default storage.
- A name that can't resolve,
  e.g., it refers to a resource the owner doesn't have,
  is an error from `calkit push`.
  A plain `dvc push` with an unknown name doesn't fail;
  its files go to the default storage and get moved later.
- The hub keeps a record of every resource a project has used,
  and reads fall back across all of them,
  which is what makes moving files lazily safe.
  The reconcile loop runs when the mapping changes and after Git pushes,
  triggered by `calkit push` notifying the hub,
  or by a webhook from the Git host.
  Nothing needs to move before the next push works,
  so a move can be slow, retried, or skipped.
- The optional `hub` key is for federation
  ([#1252](https://github.com/calkit/calkit/issues/1252)).
  It means another login,
  so it should be rare.
- Built-in names work with no setup and go to their natural home:
  `git` to the project's Git repo,
  `dvc` to calkit.io,
  and `git-lfs` to the Git host's LFS, e.g., GitHub's.
  The Git host's LFS uses the same auth as the Git remote,
  so the hub isn't involved.
  Configuring one,
  e.g., `git-lfs: {name: my-hf-bucket}`,
  sends it to connected storage instead,
  and only then does Calkit write a `.lfsconfig` pointing LFS at the hub.
  Moving LFS files off GitHub this way is the same background move as any
  other storage change.
  When Git LFS is needed but not set up,
  Calkit handles it in three parts.
  Installing the `git-lfs` binary goes through the `calkit/install.py`
  registry,
  so it's prompted, opt-in, and recorded in `~/.calkit/installed.json`
  (Homebrew on macOS, winget `GitHub.GitLFS` on Windows,
  though Git for Windows usually bundles it).
  On Linux, offer a choice among the package managers that are present:
  registry entries grow from one command per platform to a list of
  options,
  each gated on a package manager found with `shutil.which`.
  One found means prompt as today,
  several means let the user pick,
  and none means fall back to an upstream script or a manual link.
  For git-lfs:
  `pixi global install git-lfs`, `conda`/`mamba` (conda-forge),
  and Linuxbrew first,
  since they don't need `sudo`,
  which matters on HPC clusters;
  then `apt`, `dnf`, `pacman`, and `zypper`,
  with the prompt making clear when a command uses `sudo`.
  This generalizes to the rest of the registry.
  `git lfs install --local` and `git lfs track <path>` only touch the
  repo,
  so they run automatically without a prompt,
  leaving the user's global Git config alone.
  Check on `calkit add --to git-lfs`,
  when a `git-lfs` output is added to the pipeline,
  on `calkit clone` and `calkit pull` when `.gitattributes` uses LFS,
  and in `calkit check reqs` and the `calkit run` preflight,
  since using LFS is an implicit `app` requirement.
  The clone case matters most:
  without git-lfs,
  users silently get pointer files that look like corrupt data,
  so Calkit should detect those and offer the fix,
  then run `git lfs pull`.
  GitHub LFS caveats worth documenting:
  separate storage and bandwidth limits that clones and CI count against,
  and deleting LFS objects requires deleting and recreating the repo or
  contacting support
  ([GitHub docs](https://docs.github.com/en/repositories/working-with-files/managing-large-files/removing-files-from-git-large-file-storage)).
- Users pick storage, not a tracking mechanism,
  and Calkit picks the mechanism from the storage kind.
  `git`, `dvc`, `dvc-zip`, and `git-lfs` are built-in storage instances,
  and a user-defined entry gets its mechanism from its resource,
  e.g., a bucket, or HF Datasets through the MD5 index, means DVC.
  `calkit add --to` grows from `git`, `dvc`, and `dvc-zip` to any storage
  name.
  Internally, not every mechanism works with every storage kind:

  | Content          | Git              | S3, HF bucket, Drive, OneDrive, Box | HF Datasets           |
  | ---------------- | ---------------- | ----------------------------------- | --------------------- |
  | Git-tracked      | Yes              | No                                  | Yes (whole repo)      |
  | DVC              | No               | Yes                                 | Yes (MD5 index)       |
  | Git LFS          | Yes (host's LFS) | Yes                                 | Yes (natively)        |
  | Issues (git-bug) | Yes              | Not practically                     | Unknown (custom refs) |

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
- CLI: `calkit hub list storage` lists the account's resources,
  and `calkit update storage --name {entry} {resource}` sets an entry in
  `calkit.yaml`,
  e.g., `--name dvc` for the default,
  or `--name big-data` for a new one.
  `calkit add --to {entry}` assigns a path.
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
- Where the index lives:
  the HF repo is the source of truth,
  and the hub's index is a cache built from it.
  The project's `dvc.lock` and `.dvc` files are committed into the HF repo
  alongside the data,
  with the project commit SHAs in each HF commit message,
  so any HF revision says which MD5 lives at which path,
  and the index can be rebuilt from HF alone
  (no lock-in, and nothing critical to back up on the hub).
- Tampering: an index in the HF repo can be edited by anyone with write
  access to it,
  including through HF's web editor,
  while the hub's database is harder to reach but is more state to manage.
  Checking on download makes this mostly moot:
  DVC requests every object by MD5,
  so the `ck` client hashes what it downloads and rejects a mismatch.
  The hub can also check index entries against the SHA-256 HF stores for
  every LFS file.
- History rewrites on the HF side,
  e.g., squashing to reclaim space,
  break the index.
  The hub should detect that (the revision disappears) and re-upload or
  mark the objects missing.
- HF allows 128 repo commits per hour
  ([rate limits](https://huggingface.co/docs/hub/rate-limits)),
  so mirroring must batch one HF commit per push,
  not one per project commit.
  The HF commit message lists every project commit SHA it covers.
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
- The trade-off between the two is convenience vs. scope,
  but HF's `contribute-repos` OAuth scope may remove it:
  "Create repositories and access those created by this app.
  Cannot access any other repositories unless additional permissions are
  granted."
  HF calls buckets a repo type,
  so with that scope the hub could create the `calkit` bucket and HF
  Datasets repos,
  and touch nothing else.
  Users pick which orgs to grant during authorization,
  or the hub can request one with `orgIds`.
  To verify: does `contribute-repos` cover buckets,
  and can a repo the user created by hand be granted later?
  If it works,
  the Option 1 warning in the user docs goes away,
  and Option 2 becomes a fallback.
- One resource per account rather than one bucket per project,
  so the credentials never need to create buckets on the fly.
- For `s3`, the hub signs URLs itself with the stored credentials.
  Signing is local, so there's no HF API call per file,
  and the client's existing `presigned-url` and `presigned-multipart`
  access kinds may work unchanged.
- Xet is how HF storage gets efficient,
  and it only helps transfers if the client does the chunking.
  Xet splits files into ~64 KB content-defined chunks,
  and a Xet-aware client checks which chunks already exist
  (in the session, a local cache, and a global query)
  before uploading,
  so a new version of a large file only uploads what changed.
  New chunks are compressed into 64 MB xorbs.
  This is exactly the DVC pain point in
  [#675](https://github.com/calkit/calkit/issues/675):
  DVC sees a changed file and re-uploads all of it.
  Uploads through the S3 gateway or plain HTTP don't get the transfer
  savings.
- So HF storage should use a new `hf-xet` access kind in `fs/ops`,
  for both buckets and Datasets,
  rather than presigned S3 URLs.
  The hub requests a short-lived Xet token with the owner's HF credential
  from `GET /api/buckets/{ns}/{name}/xet-write-token`
  (Datasets: `/api/datasets/{ns}/{name}/xet-write-token/{revision}`),
  and returns `casUrl`, `accessToken`, and `exp`.
  Xet tokens are scoped to one repo (and ref),
  so a collaborator's token can't reach anything else,
  and the owner's HF credential never leaves the hub.
- Upload flow:
  the client runs `hf_xet.upload_files()` with that token,
  which returns each file's Xet hash and size,
  then reports `{md5: (xet_hash, size)}` back to the hub.
  The hub registers the paths with the owner's credential:
  `POST /api/buckets/{id}/batch` with `addFile` entries
  (path `{owner}/{project}/files/md5/...`) for buckets,
  or a commit with Xet file entries at the real paths for Datasets,
  batched per push.
  A Xet write token can upload chunks but can't register paths,
  so what ends up in the owner's bucket or repo always goes through the
  hub.
- Download flow:
  the hub returns a read token and the file's Xet hash,
  and the client runs `hf_xet.download_files()`.
  With hf_xet's chunk cache,
  pulling a new version of a large file only downloads the changed
  chunks.
  To verify: the chunk cache's default size and location,
  since it's separate from the DVC cache and uses more disk.
  Downloads are also checked against the MD5 by the `ck` client.
- Verified 2026-09-26 against an HF bucket with `hf-xet` 1.4.3
  (script playing both hub and client roles):
  the owner's token mints a bucket Xet write token (15 minute lifetime);
  a 32 MiB upload transferred 32 MiB;
  re-uploading it with 1 MiB changed in the middle transferred 1.1 MiB;
  registering a path with only the Xet token was rejected (401),
  while the owner's token worked (200);
  a download with a read token matched the MD5;
  and `deleteFile` cleaned up.
  So the brokered flow works as designed,
  and collaborators holding Xet tokens can't write paths.
- Client dependency: `hf-xet`,
  a standalone Rust wheel (`huggingface_hub` isn't needed),
  with wheels for macOS, Linux, and Windows.
  Make it a regular dependency so there's nothing for users to install.
  DVC transfers one object per `put_file` call,
  which gives up hf_xet's within-session batching;
  batching in the `ck` filesystem can come later.
- With Xet, connecting an HF account with OAuth (Option 1) is enough,
  since the hub mints Xet tokens with the OAuth token,
  so S3 credentials (Option 2) are only needed for other S3 providers.
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
- First PR (MVP): swap a project's DVC storage from the hub's internal
  bucket to an HF bucket, configured entirely on the hub.
  No `calkit.yaml` changes.
  The client gets the `hf-xet` access kind and the `hf-xet` dependency,
  so transfers get Xet's savings from the start,
  and HF Datasets in the next PR reuse the same transfer path.
- MVP, connecting HF:
  an HF OAuth connect flow alongside the existing Google and Zenodo ones
  (`hub/frontend/src/components/UserSettings/ConnectedAccounts.tsx`,
  a code-exchange route in `hub/backend/app/api/routes/users.py`,
  and a getter with refresh like `users.get_google_token`),
  storing the token in the encrypted `UserExternalCredential` table
  (`hub/backend/app/models/core.py:153`).
  Request `contribute-repos` if it covers buckets,
  otherwise `manage-repos`.
- MVP, storage resources:
  a new `StorageResource` table owned by a user or org account
  (kind `hf-bucket`, namespace, bucket, credential reference).
  Adding one creates the `calkit` bucket if needed,
  and checks the credential by requesting a Xet write token.
- MVP, project binding:
  a nullable `Project.dvc_storage_id`
  (null means the internal bucket),
  plus a record of every resource the project has ever used,
  for read fallback.
  Only the owner can change it.
  One Alembic migration,
  per `hub/docs/dev/database-migrations.md`.
- MVP, `fs/ops`:
  resolve the project's resource where the TODO is
  (`hub/backend/app/api/routes/projects/fs.py:198`).
  For HF buckets,
  `exists`, `info`, `list`, and `find` use the bucket's metadata
  (`HfFileSystem` with `hf://buckets/` paths, or the Hub API),
  `put` returns `hf-xet` write access,
  `get` returns `hf-xet` read access,
  and a new `register` operation takes the Xet hashes after an upload.
  `backend: "hf"` is already in the `FsOpResponse` literal.
- MVP, read fallback:
  `exists`, `info`, and `get` check the current resource first,
  then previous ones, including the internal bucket,
  so switching needs no data move.
  `list` and `find` merge results across them.
- MVP, the other callers:
  about 60 call sites outside `storage.py` assume the internal bucket,
  e.g., the file, figure, and pipeline views in
  `hub/backend/app/api/routes/projects/core.py`,
  `projects.py`, `dvc.py`, and `pipeline.py`.
  They need a per-project way to read a file or get a browser URL,
  or HF-backed projects will show missing files in the UI.
  For HF, the hub can read with the owner's credential,
  and give browsers the CDN URL HF redirects to.
  The legacy HTTP DVC remote (`api/routes/projects/dvc.py`)
  can refuse HF-backed projects,
  since it streams bytes through the hub.
- MVP, usage and quota:
  usage is `du` on the owner's prefix in the internal bucket
  (`storage.py:383`),
  so HF-stored files already don't count against the Calkit plan.
  Existing gap, not this PR's:
  `fs/ops` puts don't check the quota at all;
  only the legacy remote does.
- MVP, frontend:
  there's no project settings page today.
  Add `routes/_layout/$accountName/$projectName/_layout/settings.tsx`
  with an entry in `components/Common/SidebarItems.tsx`,
  shown only to the owner,
  with a DVC storage picker listing the account's resources
  (HF Datasets shown as coming soon).
- Deleting and garbage collection:
  `fs/ops` intentionally has no `delete`,
  so no client can ever remove data,
  even though the client's `rm_file` sends one (`calkit/fs.py:946`).
  Keep it that way.
  Users still need to clean up hub storage to stay under their plan's
  limits,
  so garbage collection should be an explicit,
  owner-only action run by the hub,
  which can see every branch, tag, and release,
  unlike `dvc gc` on a clone.
  An object is kept if any of these reference it:
  `dvc.lock` or `.dvc` files at any ref,
  releases,
  other projects that import from this one,
  and forks that fall back to this project's storage.
  Archived objects,
  e.g., on Zenodo ([#1161](https://github.com/calkit/calkit/issues/1161)),
  can be removed from hub storage,
  since they can be restored from the archive.
  Always show a dry run with the size to be freed and ask to confirm,
  then move objects to a trash prefix that's emptied after a grace
  period,
  e.g., 30 days,
  rather than deleting them right away.
  For HF-backed projects,
  the same applies through the bucket `batch` API's `deleteFile`,
  but that storage doesn't count against Calkit limits,
  so it's lower priority.
- Related issues:
  [#791](https://github.com/calkit/calkit/issues/791),
  [#1253](https://github.com/calkit/calkit/issues/1253),
  [#675](https://github.com/calkit/calkit/issues/675),
  [#394](https://github.com/calkit/calkit/issues/394).
