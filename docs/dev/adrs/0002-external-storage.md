# ADR 0002: External storage

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

<!-- TODO: needs human review -->

- Status: accepted
- Date: 2026-11-22
- Issues: #1739 (Hugging Face buckets)
- User docs: [storage.md](../../storage.md)

## Context

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

HF is the first provider, in #1739.
S3 and S3-compatible storage, Box, Dropbox, OneDrive, and Google Drive
follow, so the model has to fit all of them.

## Decision

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
| HF, with a token scoped to one bucket | namespace                         | The token can't create buckets                                                          |
| S3 and compatible                     | namespace bucket                  | Creating buckets takes broader permissions, and institutions usually provide one bucket |
| Box, Dropbox, OneDrive, Google Drive  | namespace folder, e.g., `Calkit/` | Their narrower OAuth scopes are limited to a folder like this                           |

A service may offer the other kind as an option,
e.g., a dedicated S3 bucket when the credential can create one.

### Names

Names in storage stay human readable,
so people can find their files with the service's own tools,
without Calkit:

- A dedicated bucket is named after its project,
  e.g., `{hf-namespace}/{project}` on HF.
- In a namespace resource, each project's folder is
  `{owner}/{project}/`.
- Objects keep DVC's layout under that,
  i.e., `files/md5/{2 characters}/{rest of hash}`.

Projects are rarely renamed today.
Renaming a project or moving it to another owner will have to rename its
storage too, along with other things that carry its name,
e.g., its GitHub repo.
That's left for when renaming is supported.

### Visibility

A dedicated resource's visibility follows its project's:
a public project gets a public bucket,
and making a project public or private changes its bucket to match.
A namespace resource is always private,
since it holds other projects too,
so the hub gives out access to a public project's objects itself.

A public bucket exposes every object the project has ever pushed,
not only those its current version uses.
Users who don't want that can remove old objects with `dvc gc`,
or keep the project private and publish a release.

### Permissions

- Adding or removing a connection takes the right to manage the Calkit
  account, i.e., being the user, or an owner or admin of the org.
- A project owner can create a dedicated resource for their project
  under a connection belonging to the account that owns the project.
- Collaborators never get a connection's credential.
  The hub gives clients short-lived access scoped to a project's storage,
  e.g., a Xet token for one HF bucket,
  and clients reuse it and batch transfers until it nearly expires.
  Anything the scoped access can't do,
  e.g., adding paths to an HF bucket,
  the client asks the hub to do in batches.

### Changing storage

Changing a project's storage only affects new objects.
Reads fall back through the current resource,
then each previous one, newest first, then the hub's own storage,
so nothing has to move.

### Deleting

Deleting a project offers to delete its storage too:
its dedicated resource,
or its folder in a namespace resource.
Leaving it in place is also an option.

### Released datasets

Publishing a dataset,
e.g., to an HF Datasets repo with its files at their real paths and a
dataset card,
is a separate feature from storage.
A storage resource holds DVC objects by hash,
which only make sense to DVC.

### Open questions

- What happens to a connection's resources,
  and the projects using them,
  when the connection is removed.
  Today, storage a project has used can't be removed,
  but the credential behind it can, which makes it unreachable.
- What happens to an org's connection when the member who connected it
  leaves the org, for services like HF where the credential is that
  member's own.
- What to do when a dedicated bucket's name is already taken,
  e.g., by a bucket the user made themselves.

## Consequences

- One brokered pattern serves every provider:
  the hub holds credentials and hands out narrow, short-lived access,
  and clients transfer directly with the service.
- Each provider needs code for creating resources,
  changing their visibility where it applies,
  and handing out scoped access.
- HF projects get per-project buckets,
  so their usage shows up per project in HF's own billing,
  and a public project's data can be fetched straight from HF.
- Renaming or moving projects gets harder,
  since storage carries their names.

## Alternatives considered

- **One HF bucket per account** for every project,
  which #1739 first built.
  It keeps the credential from ever having to create buckets,
  but the bucket has to stay private even when projects in it are
  public, and it can't follow each project's visibility.
- **Keys in local config**, like the Overleaf integration uses.
  It needs no hub traffic,
  but the hub could never show files stored this way,
  and every collaborator would need their own credential.
- **Storage IDs instead of names** in paths and buckets,
  which would make renames free,
  but leave storage unreadable outside Calkit.
