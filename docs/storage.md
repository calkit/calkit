# Storage

Calkit keeps the history of every file in your project.
By default,
small text files like code and LaTeX source,
and figures under 1 MB,
go to the project's Git repo,
and everything else,
e.g., datasets, larger figures, and simulation results,
goes to the Calkit Hub (calkit.io).

<!-- TODO: needs human review -->

Those larger files can also go somewhere else,
e.g., a Hugging Face bucket, Box, or an S3 bucket.

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
   create a new Hugging Face bucket,
   or click "Use Box" or "Use S3 bucket."

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
Calkit doesn't remove old files from a bucket,
so delete them on HF if you need to.

If you disconnect your HF account while projects are storing files with it,
you'll need to choose whether to transfer those files to Calkit Hub storage
or leave them on HF, where those projects can no longer reach them.
Either way, your buckets stay on HF.
To switch to a different HF account,
disconnect the current one first.

Connecting your HF account gives Calkit access to everything in that HF
account or organization.

### Already using DVC?

<!-- TODO: needs human review -->

A DVC project can use a Hugging Face bucket through Calkit,
so collaborators don't need HF keys of their own:

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
A separately installed `dvc` can't use the hub remote,
and stops with an error in a project whose hub remote starts with `ck://`,
as new ones do,
so run DVC commands with `calkit dvc` instead, e.g., `calkit dvc status`.

<!-- TODO: needs human review -->

HF buckets also have an
[S3-compatible API](https://huggingface.co/docs/hub/storage-buckets-s3),
so DVC can use one as an S3 remote with your own keys,
e.g., to leave Calkit
(see [Using DVC without Calkit](#using-dvc-without-calkit)).
Through Calkit there's less to set up,
and collaborators and CI don't need the bucket's keys.

## Box

<!-- TODO: needs human review -->

Many universities give everyone Box storage,
so a project's files can live alongside the rest of your work there.
Usage counts toward your Box storage, not your Calkit plan.

To use it,
go to the project's settings on the hub and click "Use Box,"
connecting your Box account if asked,
then click it again.
Files go in a folder named `Calkit` at the top of your Box,
under the project's owner and name,
and every project you send to Box shares that folder.
You can move or rename it in Box,
and Calkit will still find it.

The folder stays private even if the project is public.
Calkit gives people who can see the project access to its files,
so they don't need Box accounts.
Each file can be as large as your Box plan allows,
e.g., 250 MB on a free account,
and Box allows about 240 uploads a minute,
so pushing thousands of small files takes a while.

If your Box account belongs to an institution,
it may need to approve Calkit first.
If Box says the app has been disabled by your administrator,
ask your IT department to enable it.

Box connections lapse after 60 days without use,
so Calkit keeps yours active.
If it does lapse, connect Box again.
Disconnecting works like it does for Hugging Face,
and your files stay in Box either way.

Connecting your Box account gives Calkit access to everything in it,
but Calkit only uses the `Calkit` folder,
and collaborators only get access to their project's folder,
for an hour at a time.

## S3

<!-- TODO: needs human review -->

Any storage that works with S3 can hold a project's files,
e.g., Amazon S3, the
[Open Storage Network (OSN)](https://openstoragenetwork.github.io),
Cloudflare R2, Wasabi, or MinIO.
Usage is billed by the provider and doesn't count against your Calkit plan.

To use a bucket,
go to the project's settings on the hub and click "Use S3 bucket."
Paste in the bucket's endpoint URL, leaving it blank for AWS,
and an access key ID and secret access key,
then enter the bucket, e.g., `s3://my-bucket` or `s3://my-bucket/calkit`.
For OSN,
these are on your allocation's page in the OSN portal.
Calkit saves the keys under a name,
so you can use them for other projects without pasting them again,
and replace or remove them under connected accounts in your
[hub account settings](https://calkit.io/settings).

Each project gets its own folder in the bucket,
under the project's owner and name,
so many projects can share one bucket.

If the keys can only read the bucket,
Calkit reads files from it but sends new files where they went before.
This is how to share data in a bucket you don't control,
e.g., with read-only keys from a data provider,
without giving the keys to anyone.

Files go directly between your machine and the bucket,
using links Calkit signs with your keys.
Collaborators never see the secret key.

To show the contents of files stored with DVC on calkit.io,
e.g., tables,
the bucket has to allow requests from calkit.io in its CORS rules,
e.g., with the AWS CLI:

```sh
aws s3api put-bucket-cors --bucket my-bucket --cors-configuration \
  '{"CORSRules": [{"AllowedOrigins": ["https://calkit.io"], "AllowedMethods": ["GET"]}]}'
```

For storage other than AWS, add `--endpoint-url` with its endpoint.
Without the rule, pushing and pulling still work.
Disconnecting keys works like it does for Hugging Face,
and your files stay in the bucket either way.

## Changing where files are stored

<!-- TODO: needs human review -->

Only the project owner can change where its files are stored,
since it uses their storage.
New files go to the new storage right away,
and existing files stay where they are.
Calkit still finds them there,
so you and your collaborators don't need to do anything.

When deleting a project,
you can choose to delete its files from Calkit Hub storage too.
Calkit never deletes anything from storage you've connected,
so if you no longer need a project's bucket or folder,
delete it on HF, Box, or your S3 provider.

## Using your storage without Calkit

<!-- TODO: needs human review -->

Your files are always stored in a standard layout that DVC understands,
so you're never locked in to Calkit.
To get them without Calkit,
download them into the project's DVC cache
with the storage service's own tools and your own login.

### Using DVC without Calkit

<!-- TODO: needs human review -->

DVC can also use a project's S3 or HF bucket as a remote of its own,
since the files in it are laid out like any other DVC remote.
This takes more setup than going through Calkit,
and everyone using the remote needs keys,
but it works alongside Calkit or as a way to leave it.
In an S3 bucket,
a project's files are under its owner and name in lowercase,
e.g., `s3://my-bucket/calkit/my-org/my-project`
for a project using `s3://my-bucket/calkit`.
In an HF bucket Calkit created,
they're at the root of the bucket.

To keep the keys out of the project,
put them in a profile in `~/.aws/credentials`:

```ini
[my-bucket]
aws_access_key_id = {access key ID}
aws_secret_access_key = {secret access key}
```

Then add the bucket as a remote in the project,
leaving out `endpointurl` for AWS.
While the project has the hub remote,
use `calkit dvc` rather than a separately installed `dvc`:

```sh
calkit dvc remote add my-bucket s3://my-bucket/calkit/my-org/my-project
calkit dvc remote modify my-bucket endpointurl https://s3.example.org
calkit dvc remote modify my-bucket profile my-bucket
```

For an HF bucket,
use HF's S3 gateway,
with keys made from an HF access token
by selecting "Generate S3 credentials" next to it in your
[HF token settings](https://huggingface.co/settings/tokens).
The keys can read, or read and write,
whatever the token can.
The endpoint has the bucket's HF username or organization in it,
and the remote URL has only the bucket's name:

```sh
calkit dvc remote add hf-bucket s3://my-project
calkit dvc remote modify hf-bucket endpointurl https://my-org.s3.hf.co
calkit dvc remote modify hf-bucket region us-east-1
calkit dvc remote modify hf-bucket profile hf
```

The gateway only takes path-style requests,
and can't read the checksums recent versions of DVC's S3 client send by
default,
so set both for the profile in `~/.aws/config`,
along with its keys in `~/.aws/credentials` under `[hf]`:

```ini
[profile hf]
s3 =
    addressing_style = path
request_checksum_calculation = when_required
response_checksum_validation = when_required
```

Then `calkit dvc push -r {remote}` and `calkit dvc pull -r {remote}`
send and get files with the bucket directly.
While it's the project's storage on the hub,
Calkit finds files in the same folder,
so files pushed with DVC can be pulled with Calkit, and the other way
around.
Keep the hub as the default remote,
so `calkit push` and `calkit pull` keep working for collaborators without
keys.

To leave Calkit for plain DVC,
run `calkit pull`,
then `calkit dvc push -r {remote}`
to copy the files this version of the project uses into the bucket,
since files pushed before the project used it stay where they were
(see [Changing where files are stored](#changing-where-files-are-stored)).
Then make the bucket the default remote and remove the hub's,
named `calkit`,
after which `dvc` works on its own:

```sh
calkit dvc remote default {remote}
calkit dvc remote remove calkit
```

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
- Connecting AWS without creating access keys
- Connecting an existing HF bucket to a project with a token limited to it
- Choosing storage per path, e.g., one dataset on HF and the rest on
  calkit.io, in `calkit.yaml`
- Moving files to new storage when a project's storage changes
- Removing files a project no longer uses from Calkit Hub storage
- Choosing storage for a fork
- Releasing to HF Datasets
- Keeping the project's Git repo on GitLab, Codeberg, HF, or calkit.io
  ([#1254](https://github.com/calkit/calkit/issues/1254))
