# Hub storage

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

<!-- TODO: needs human review -->

Where the Calkit Hub keeps projects' files,
why it works this way,
and where it's probably headed.
Today that's a project's large files, stored with DVC;
its Git repo is always on GitHub.

- User docs: [storage.md](../../storage.md)
- Issues: #1739 (Hugging Face buckets), #2170 (Box), #1253 (own cloud
  storage), #1254 (own Git host), #1390 (no GitHub account), #682
  (Forgejo), #654 and #736 (issues in the project)
- Notes on later work, e.g., storage per path, Git LFS, and HF Datasets:
  [original design notes](https://github.com/calkit/calkit/blob/55e3628d1665fb5e72ca1f4cc74acea94810af0a/docs/storage.md#design-notes)

## Why

A project's large files are stored with DVC.
By default they go to the Calkit Hub's own object storage,
which counts toward the owner's plan limit.
Users want them elsewhere:
storage they already pay for, e.g., an institution's S3 bucket,
storage with a free allowance, e.g., Hugging Face (HF) buckets,
or a service their collaborators already use,
e.g., Box, Dropbox, OneDrive, or Google Drive.

The hub has to stay aware of where every object is,
so it can show a project's files, figures, and pipeline status
no matter where they're stored.
Configuring storage only on users' machines,
e.g., with a key in local config, would hide those files from the hub.
At the same time, traffic through the hub should scale with batches of
files, not with files or bytes.

The model has to fit every provider,
from object storage like S3 and HF buckets
to file services like Box, Dropbox, OneDrive, and Google Drive.

So:

- One brokered pattern serves every provider:
  the hub holds credentials and hands out narrow, short-lived access,
  and clients transfer directly with the service.
- Each provider needs code for creating resources,
  changing their visibility where it applies,
  and handing out scoped access.
- A public project's objects in a dedicated public bucket can be fetched
  straight from the service, without the hub.
- Renaming or moving projects gets harder,
  since storage carries their names.

## Where we are

<!-- TODO: needs human review -->

The hub's own storage, HF buckets, Box, and S3 and S3-compatible storage,
e.g., the Open Storage Network (OSN), hold DVC objects.

### Terms

- A **service** is something Calkit integrates with,
  e.g., HF, AWS, or Box.
  The Calkit Hub is a service too.
- An **account** is someone's identity on a service.
  Users and orgs have accounts on the Calkit Hub,
  and an external account on each service they connect.
- A **connection** links a Calkit account to an external account,
  with the credential the hub uses to act on it.
  It belongs to the Calkit account,
  with a record of the user who connected it.
  An account can have several connections,
  including several to the same service, e.g., two AWS accounts.
- A **storage resource** is a place under a connection where DVC objects
  go, one of two kinds:

  - **dedicated**: a bucket or folder holding one project.
  - **namespace**: a bucket or top-level folder holding many projects,
    each in its own folder.

  The hub's own storage is a built-in namespace resource every account
  starts with.

- A project uses one storage resource for new objects,
  and the hub keeps a record of every one it has used before.

### Defaults by provider

| Service                               | Default kind                      | Reason                                                                                  |
| ------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------- |
| HF, connected with OAuth              | dedicated bucket                  | HF doesn't limit bucket count, and a bucket's visibility can match its project's        |
| HF, with a token scoped to one bucket | dedicated bucket                  | The token can't create buckets, and a Xet read token covers a whole bucket              |
| S3 and compatible, with pasted keys   | namespace bucket or prefix        | Creating buckets takes broader permissions, and institutions usually provide one bucket |
| Box                                   | namespace folder, e.g., `Calkit/` | Tokens can be downscoped to one project's folder, so projects can share it              |
| Dropbox, OneDrive, Google Drive       | namespace folder, e.g., `Calkit/` | Their narrower OAuth scopes are limited to a folder like this                           |

A service may offer the other kind as an option,
e.g., a dedicated S3 bucket when the credential can create one.
HF is the exception,
and its buckets are always dedicated.
A Xet read token covers a whole bucket,
so a reader of one public project in a shared bucket could fetch another
project's content if they knew its Xet hash.

<!-- TODO: needs human review -->

Box has no OAuth scope narrower than the whole account,
so the hub holds a token for all of it.
Clients only get tokens downscoped to one project's folder.

### Layout

Names in storage stay human readable,
so storage can be used with the service's own tools:

- A dedicated bucket is named after its project,
  e.g., `{hf-namespace}/{project}` on HF,
  and holds the project's objects at its root.
- In a namespace resource, each project's objects are under
  `{owner}/{project}/`.
- Objects keep DVC's layout under that,
  i.e., `files/md5/{2 characters}/{rest of hash}`.
- Clients always see paths as `{owner}/{project}/...`,
  whichever kind of resource the objects are in.

Box addresses items by ID, not path,
so the hub keeps the ID of a Box namespace folder rather than its path,
and paths under it are resolved by listing folders.
The folder can then be moved or renamed in Box.
Since nothing is deleted from it,
a project's folder can outlive the project,
so each holds a `.calkit-project` file with its project's ID,
and a project can't start using a folder that holds another's files,
e.g., a deleted project's with the same name.

Creating a dedicated bucket fails if the name is taken.
The hub doesn't adopt the existing bucket,
since it would write into it and could expose what's there by changing its
visibility.

Projects are rarely renamed today.
Renaming a project or moving it to another owner will have to rename its
storage too, along with other things that carry its name,
e.g., its GitHub repo.
That's left for when renaming is supported.

### Visibility

The hub keeps the visibility of a dedicated resource it created in sync
with its project's, wherever the service supports it.
A namespace resource stays private,
since it holds other projects too,
and a resource the hub didn't create,
e.g., an HF bucket connected with a token limited to it,
keeps the visibility its owner gave it.
For both, the hub gives out access to a public project's objects itself.

### Access

Clients never get a connection's credential.
The hub gives them short-lived access scoped to a project's storage,
e.g., a Xet token for one HF bucket,
and they reuse it and batch transfers until it nearly expires.
Anything the scoped access can't do,
e.g., adding paths to an HF bucket,
clients ask the hub to do in batches.

<!-- TODO: needs human review -->

A Box token downscoped to a project's folder can do everything a client
needs there, i.e., make folders, upload, list, and download,
so Box needs nothing from the hub after the token.
Clients look up where many objects are in one request to the hub,
and download each by its Box ID.

<!-- TODO: needs human review -->

S3 has no OAuth, so users paste access keys.
Keys reach one endpoint, e.g., an OSN pod or AWS,
and a user can save several sets, each under a name.
A project selects a set of keys and a bucket with an optional prefix,
which is a namespace.
The hub signs URLs with the keys,
so clients transfer directly with the bucket.
Writing a file in the project's folder shows whether the keys can write,
since its `.calkit-project` file may already be there;
storage they can only read is added to the project's previous storage,
so it's read from but never written to.
The hub only reaches endpoints on the public internet,
checking each connection's address as it's made,
since it would otherwise make requests into its own network for users.

### Keeping connections alive

<!-- TODO: needs human review -->

Box refresh tokens work once and lapse after 60 days unused,
so a project nobody touches for that long would lose its storage.
A daily job on the worker, queued by `rq cron` rather than left waiting in
Valkey, which can evict it, refreshes connections unused for a month.
Only a rejected refresh token lapses a connection,
which keeps its record so the Box account it was is still known.
Refreshes of one connection take turns under a row lock,
since a second refresh with the same token would disconnect it.

### Changing storage

Changing a project's storage only affects new objects.
Reads fall back through the current resource,
then each previous one, newest first, then the hub's own storage,
so nothing has to move.

### Removing a connection

Removing a connection would make its resources unreachable,
so the hub refuses until it's told what to do with them:
transfer their objects to the hub's own storage,
or leave them where they are and forget the resources.
A transfer runs on the worker,
since it can take as long as the data takes to copy.
The hub keeps the credential until the copy is done.
The job switches each resource's projects to the hub's own storage just
before copying it,
so new objects land there while reads still fall back to the old
resource,
and the resources can't be selected again or added to until it's done.
The copy skips objects already copied,
so a failed transfer can be rerun,
and its status is read from the job.

Two other events would strand a connection's resources the same way:

- Removing an org member whose credential a connection uses.
  This takes the same choice, from an org admin,
  and isn't built yet.
- Reconnecting a service as a different external account.
  The hub refuses while resources use the old account,
  so it has to be removed first.

### Deleting storage

The hub never deletes anything from a connected service,
including resources it created.
A connection's credential can reach far more than Calkit's storage,
e.g., every repo in an HF account,
a service may identify a resource by a name that can be reused,
and a deletion there usually can't be undone.
The hub only deletes from its own storage,
and stops using a connected resource by removing its record.
People delete connected resources with the service itself.

### Released datasets

Publishing a dataset,
e.g., to an HF Datasets repo with its files at their real paths and a
dataset card,
is a separate feature from storage.
A storage resource holds DVC objects by hash,
which only make sense to DVC.

<!-- TODO: needs human review -->

## Where we want to end up

### More storage

- Dropbox, OneDrive, and Google Drive, as namespace folders.
- Connecting AWS without access keys, e.g., with a role the hub assumes.
- Connecting an existing HF bucket with a token limited to it.
- Choosing storage per path in `calkit.yaml`,
  e.g., one dataset on HF and the rest on the hub.
- Moving files to new storage when a project's storage changes.
- Pasting what an OSN allocation's page in ColdFront shows,
  i.e., endpoint, bucket, and keys, in one go.

### Git storage

A project's Git repo should be pluggable the same way,
so GitHub becomes one option rather than a requirement:

- The hub hosts Git itself as the default,
  the way its own storage is the default for DVC,
  which also lets people use Calkit without a GitHub account.
- GitHub, GitLab, hosted or self-hosted, and Forgejo,
  which covers Codeberg and Gitea,
  plug in as external Git storage.
  Hosted services connect with OAuth,
  and self-hosted ones with pasted tokens,
  since registering an OAuth app there takes the instance's admin.
- Collaborators push and pull through the hub,
  e.g., `calkit.io/git/{owner}/{project}.git`,
  authenticated as themselves with their Calkit login.
  The hub checks their access to the project,
  then forwards to the host with the connection's credential,
  scoped to one repo where the host allows it,
  e.g., a GitLab project access token or a Forgejo deploy key.
  This is the same brokered pattern as DVC storage:
  collaborators don't need accounts on the host,
  and the credential never leaves the hub.

The costs are that Git traffic goes through the hub,
which is small next to data but not free,
and that pushes, issues, and pull requests made through the hub show up
on the host as the credential's identity,
though commits keep their authors.

### Issues

Issues should live in the project,
e.g., as files under `.calkit/`,
so they move with it and work offline,
and sync with each Git host's issue tracker through its connection.
git-bug, which keeps issues in Git and has bridges to GitHub and GitLab,
is worth evaluating before building this.

## Alternatives considered

- **One HF bucket per account** for every project,
  which #1739 first built.
  It keeps the credential from ever having to create buckets,
  but the bucket has to stay private even when projects in it are
  public, and it can't follow each project's visibility.
- **Deleting connected storage from the hub**,
  which #1739 first built.
  It saves a trip to the service,
  but a bug or a reused name could destroy data the hub can't restore.
- **Keys in local config**, like the Overleaf integration uses.
  It needs no hub traffic,
  but the hub could never show files stored this way,
  and every collaborator would need their own credential.
- **Storage IDs instead of names** in paths and buckets,
  which would make renames free,
  but leave storage unreadable outside Calkit.

<!-- TODO: needs human review -->

- **Keys for each project rather than each user**,
  for S3.
  Keys usually reach a whole bucket or account,
  so tying them to one project would mean pasting the same keys again for
  each project sharing a bucket.
- **Checking an S3 endpoint's address only when its keys are saved**.
  A redirect, or the host resolving differently later,
  could still point the hub at its own network,
  so each connection is checked as it's made.
- **Sharing a Git host credential with collaborators**,
  or giving each a token of their own on the host.
  It needs no proxy,
  but either spreads a credential that can do more than the project needs,
  or makes every collaborator get an account on the host.
