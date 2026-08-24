# Privacy policy for the Calkit browser extension

Last updated: 2026-08-09

This covers the [Calkit browser extension](index.md). It does not cover
[calkit.io](https://calkit.io) or any other Calkit software.

The extension exists to connect the sites where research work happens to a
Calkit hub the user already has an account on. It has no analytics, no
telemetry, and no advertising. Nothing is sent anywhere for Calkit's own
purposes, and no data is sold or shared with third parties.

## What is kept on your device

Three things, in the browser's extension storage:

- **Settings**: which Calkit hub is selected, the address of a self-hosted
  hub if you configured one, and which project is active.
- **Credentials**: the access and refresh tokens for each hub you have
  signed in to.
- **Your email address**, for each hub you are signed in to, so the
  extension can show which account it is using.

Signing out deletes the credentials and the email address for that hub.
Uninstalling the extension deletes all of it.

## What is sent, and where

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

## What is never collected

Browsing history, page contents beyond the citation metadata described
above, form input, keystrokes, location, and anything at all on sites
outside the extension's site list. The extension has no access to other
sites unless you grant it, which it asks for only when you configure a
self-hosted hub.

Your credentials never reach a web page: every request to a hub is made
from the extension's own service worker.

## Your control over this

- Signing out removes the stored credentials and email for that hub.
- Clearing the active project stops reference lookups, which need a project
  to check against.
- Uninstalling removes everything the extension stored.
- Data held in your Calkit account is governed by the privacy policy of the
  hub you use.

## Contact

Questions about this policy, or a request about data held in a Calkit
account: [help@calkit.io](mailto:help@calkit.io).

Source for the extension is at
[github.com/calkit/calkit](https://github.com/calkit/calkit/tree/main/browser-ext),
where what is described here can be checked against what it does.
