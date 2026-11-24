# ADR 0002: External storage

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

- Status: accepted
- Date: 2026-11-22
- Issues: #1739 (Hugging Face buckets)
- User docs: [storage.md](../../storage.md)
- Notes on later work, e.g., storage per path, Git LFS, and HF Datasets:
  [original design notes](https://github.com/calkit/calkit/blob/55e3628d1665fb5e72ca1f4cc74acea94810af0a/docs/storage.md#design-notes)

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
| HF, with a token scoped to one bucket | dedicated bucket                  | The token can't create buckets, and a Xet read token covers a whole bucket              |
| S3 and compatible                     | namespace bucket                  | Creating buckets takes broader permissions, and institutions usually provide one bucket |
| Box, Dropbox, OneDrive, Google Drive  | namespace folder, e.g., `Calkit/` | Their narrower OAuth scopes are limited to a folder like this                           |

A service may offer the other kind as an option,
e.g., a dedicated S3 bucket when the credential can create one.
HF is the exception,
and its buckets are always dedicated.
A Xet read token covers a whole bucket,
so a reader of one public project in a shared bucket could fetch another
project's content if they knew its Xet hash.

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

### Changing storage

Changing a project's storage only affects new objects.
Reads fall back through the current resource,
then each previous one, newest first, then the hub's own storage,
so nothing has to move.

### Removing a connection

Removing a connection would make its resources unreachable,
so the hub refuses until it's told what to do with them:
transfer their objects to the hub's own storage,
delete them,
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

HF identifies a bucket by name,
so a recorded name can come to mean a different bucket,
e.g., if one is deleted on HF and another takes its name.
Before deleting anything,
the hub checks every dedicated bucket involved,
and refuses if one was created after the hub recorded it,
or holds anything other than DVC objects.
The hub only calls HF's bucket API to delete,
never its repo API.
Deleting a project only removes external storage reached with the
deleting user's own credential,
so one member can't use another's credential to delete from their account.

### Released datasets

Publishing a dataset,
e.g., to an HF Datasets repo with its files at their real paths and a
dataset card,
is a separate feature from storage.
A storage resource holds DVC objects by hash,
which only make sense to DVC.

## Consequences

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
