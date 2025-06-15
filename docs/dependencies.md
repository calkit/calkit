# Dependencies

One major barrier to reproducibility is dependency definition and management.
If one relies too much on system-level dependencies,
this can lead to reproducibility because a full system is hard to
define with sufficient detail to reproduce.

So, our goal is to minimize system-level dependencies as much as possible,
and those that remain should be generally applicable to many projects,
e.g., Docker, uv, and of course Calkit itself.
Conversely, relying on system-wide installations of things like
Python packages is a bad idea.
For software libraries and tools more specific to a project,
use [environments](environments.md).

Dependencies can be declared in the `calkit.yaml` file
as a list in the `dependencies` section,
and these will be checked before running the pipeline when
`calkit run` is called.

Dependencies can be apps or environmental variables,
the latter being useful for configuration of a project that needs to be
unique on each user's machine,
which can also be used to avoid committing secrets to the repo.

The example below, taken from
[this project](https://github.com/petebachant/strava-analysis)
shows both a unique configuration variable (`STRAVA_CLIENT_ID`)
and a secret (`STRAVA_CLIENT_SECRET`)
that allow a different user to use copy and reuse the project without
changing anything.

```yaml
dependencies:
  - docker
  - STRAVA_CLIENT_ID:
      kind: env-var
      notes: >
        The STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET environmental
        variables can be set in the .env file after creating a Strava
        application at https://www.strava.com/settings/api
  - STRAVA_CLIENT_SECRET:
      kind: env-var
```

As we can see, a `.env` file, which is kept out of version control,
can be used to define these variables.
`calkit set-env-var` can be used as a shortcut to set one of these
in lieu of directly editing `.env`.
`calkit check env-vars` can also be run to check for missing variables,
prompting the user for their values and setting them in `.env`.
