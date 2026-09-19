# Privacy policy

Last updated: 2026-09-14

This covers the Calkit hub at [calkit.io](https://calkit.io), the Calkit
command line tool and Python package, and the Calkit browser extension.
Self-hosted hubs are run by whoever hosts them, and their own policies
apply.

Calkit is run by Pete Bachant as a sole proprietor, who is responsible for
the information described here. Questions and requests go to
[help@calkit.io](mailto:help@calkit.io).

The short version: we keep what's needed to run your account, and, only if
you allow it, a record of which features you use so we can make Calkit
better. Your data is never sold, never used for advertising, and never
shared with anyone for their own purposes.

## How usage information is used

Calkit tries to do a focused set of things well. Knowing which features
people actually use, and which they don't, is how we decide where to spend
effort: the features people rely on get improved, and the ones nobody uses
get removed, so the tools stay clean and focused rather than piling up
options.

That's the only thing usage information is for. We look at it in aggregate
(e.g., how many people ran a notebook from the hub this month), not to
watch what any one person is doing.

## The hub (calkit.io)

### What your account stores

- **Profile**: your email address, name, account name, and GitHub username
  if you signed in with GitHub. Passwords are stored only as a salted hash.
- **Connected accounts**: access tokens for services you connect, such as
  GitHub, Zenodo, Zotero, Google Drive, and Overleaf, so the hub can act on
  your behalf when you ask it to.
- **Your work**: projects, datasets, comments, questions, releases,
  notifications, organization memberships, and feedback you send.
  Project repositories themselves live on GitHub, under your account or
  organization, and large files live in the hub's object storage.
- **Subscription**: your plan, and a customer ID from our payment
  processor. Card details go directly to the payment processor and never
  reach Calkit.

### Usage information

When you first visit the hub, it asks whether you allow usage information
to be recorded. If you accept, the hub records the pages you visit and the
features you use, along with basic browser and device information and an
approximate location derived from your IP address. While you're signed in,
this is associated with your account, and includes actions recorded by the
hub's server, such as creating a project or publishing a release.

If you reject, none of it is recorded, and nothing for this purpose is
stored on your device. Once you're signed in, your choice is saved to your
account, so it applies on every device you use.

You can change your choice at any time under Settings → Privacy. Stopping
it stops future recording. To have usage information that was already
recorded deleted, email [help@calkit.io](mailto:help@calkit.io).

### Server logs

Like most web services, the hub's servers log requests, including IP
addresses, to keep the service running and secure. These logs are deleted
after 30 days.

### What's stored in your browser

- Login tokens, so you stay signed in.
- Small preferences, such as light or dark mode and where to return to
  after signing in.
- Your answer to the usage information question.
- If you allowed usage information, an anonymous identifier used to group
  your visits together.

### Who else processes your data

The hub relies on service providers for hosting and storage, payments,
email delivery, and usage analytics. They process data only to provide that
service to Calkit, not for their own purposes. When you connect an outside
account, like GitHub or Zenodo, data you send there through the hub is
governed by that service's policy.

### Why we're allowed to use it

- **Account information and your work**: needed to provide the service you
  signed up for.
- **Usage information**: only with your consent, which you can withdraw at
  any time.
- **Server logs**: our legitimate interest in keeping the service running
  and secure.

### Where it's stored

calkit.io runs on a server in the United States, and the service providers
it relies on store data in the United States as well. If you use the hub
from outside the United States, including from the EU or UK, your
information is transferred to and processed in the United States.

## The command line tool and Python package

The `calkit` CLI and Python package do not collect any usage information and
do not send anything to Calkit on their own. They contact a Calkit hub only
when you run a command that uses one, such as signing in or pushing data to
hub storage, and contact other services, like GitHub, only when you
configure and use them. The same goes for the Calkit VS Code and JupyterLab
extensions, which work through the CLI.

We may later add a way to opt in to sharing usage information from the CLI,
to help decide which features to improve or remove as described
[above](#how-usage-information-is-used). If we do, it will be off unless
you turn it on, and this page will describe exactly what it sends.

Calkit runs other tools on your behalf, which have their own policies. In
particular, [DVC](https://dvc.org/doc/user-guide/analytics) sends anonymous
usage statistics to its developers by default. To turn that off:

```sh
calkit dvc config --global core.analytics false
```

## Browser extension

The [browser extension](browser-ext/index.md) exists to connect the sites
where research work happens to a Calkit hub you already have an account on.
It collects no usage information and has no advertising. Nothing is sent
anywhere for Calkit's own purposes.

### What is kept on your device

Three things, in the browser's extension storage:

- **Settings**: which Calkit hub is selected, the address of a self-hosted
  hub if you configured one, and which project is active.
- **Credentials**: the access and refresh tokens for each hub you have
  signed in to.
- **Your email address**, for each hub you are signed in to, so the
  extension can show which account it is using.

Signing out deletes the credentials and the email address for that hub.
Uninstalling the extension deletes all of it.

### What is sent, and where

Everything below goes to the Calkit hub you selected and signed in to.
That is calkit.io unless you chose another instance, in which case it is
the one you configured, which may be run by you or your institution.

- **On a journal or preprint page** in the extension's site list: the
  paper's DOI, arXiv ID, or title, to ask whether it is already in your
  project's references. This happens when the page loads, so the extension
  can tell you whether the paper is already filed before you click.
- **On a GitHub repository page**: the repository's owner and name, to ask
  whether it is one of your projects.
- **On an Overleaf project page**: the Overleaf project ID from the URL,
  to find which Calkit project it syncs with.
- **When you save a reference**: the citation fields being saved, which
  include the page's URL.
- **When you view an artifact**: the project and file path, so the hub can
  return a short-lived link to the file.

Two other requests do not involve your data:

- The extension reads a public repository's `calkit.yaml` from
  `raw.githubusercontent.com` to tell whether it is a Calkit project. Only
  the repository name is involved, and GitHub is already serving you the
  page you are on.
- Artifacts are downloaded from the object storage your hub uses (Amazon S3
  or Google Cloud Storage), using a short-lived signed link the hub issued.

### What is never collected

Browsing history, page contents beyond the citation metadata described
above, form input, keystrokes, location, and anything at all on sites
outside the extension's site list. The extension has no access to other
sites unless you grant it, which it asks for only when you configure a
self-hosted hub.

Your credentials never reach a web page: every request to a hub is made
from the extension's own service worker.

### Your control over the extension

- Signing out removes the stored credentials and email for that hub.
- Clearing the active project stops reference lookups, which need a project
  to check against.
- Uninstalling removes everything the extension stored.

## Your choices and rights

- **Usage information**: allow or stop it at any time under Settings →
  Privacy on the hub, and ask for what was already recorded to be deleted.
- **Correcting your information**: edit your profile under Settings → My
  profile.
- **Deleting your account**: Settings → Danger zone deletes your account
  and the information stored with it. Repositories on GitHub belong to you
  or your organization and are not deleted.
- **Anything else**, including a copy of the information we hold about you,
  or a question about this policy: email
  [help@calkit.io](mailto:help@calkit.io).

## Changes to this policy

When this policy changes, the date at the top will change with it, and the
history of every change is public in the
[Calkit repository](https://github.com/calkit/calkit/commits/main/docs/privacy.md).

Calkit is open source, so what's described here can be checked against
what the software actually does at
[github.com/calkit/calkit](https://github.com/calkit/calkit).
