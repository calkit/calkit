# Cloud integration

The Calkit Cloud ([calkit.io](https://calkit.io)) serves as a project
management interface and a DVC remote for easily storing all versions of your
data/code/figures/publications, interacting with your collaborators,
reusing others' research artifacts, etc.

After signing up, visit the
[settings](https://calkit.io/settings?tab=tokens)
page and create a token for use with the API.
Then execute:

```sh
calkit config set token ${YOUR_TOKEN_HERE}
```

## Using DVC remotes other than calkit.io

It's possible to configure DVC to use a different remote storage location,
e.g., an AWS S3 bucket.
However,
any artifacts stored externally will not be viewable on calkit.io,
and permissions for these locations will need to be configured
for each collaborator manually.
