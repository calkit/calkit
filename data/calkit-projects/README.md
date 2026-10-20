# Calkit projects in the wild

Run: 2026-10-20 04:17–05:00 UTC (2026-10-19 local), by Claude (read-only).
Output: `projects.csv` (one row per distinct project; forks and
copies merged into the upstream row and listed in `notes`).

## Queries

GitHub code search (`gh api -X GET search/code -f q=... -f per_page=100`;
only indexes default branches, excludes most forks):

- `filename:calkit.yaml` (84 hits, primary)
- `path:/ filename:calkit.yaml`
- `filename:calkit.yaml environments`
- `filename:calkit.yaml publications`
- `"calkit run" filename:dvc.yaml`, `calkit filename:dvc.yaml`
- `"calkit xenv"`, `"calkit nb execute"`, `"calkit-python"`
- `"uses: calkit"`, `"calkit run" path:.github/workflows`
- `"calkit.io" filename:README.md`

GitHub repo search (`search/repositories`): `calkit`, `topic:calkit`,
`calkit in:readme`, `calkit in:description`, `calkit fork:true`.

GitHub verification (`repos/OWNER/REPO/contents/calkit.yaml`, root only):

- every candidate from the searches above, the Calkit hub, and all repos
  pushed since 2024-06-01 of each owner with a hit (664 repos)
- all branches (up to 40 per repo) of non-Pete owners' repos, to catch
  calkit.yaml on non-default branches

Calkit hub (public, unauthenticated):
`GET https://api.calkit.io/projects?limit=25&offset=N` (57 visible public
projects; reported count 81).

Zenodo (`https://zenodo.org/api/records?q=...&size=25&page=N`;
size is capped at 25 unauthenticated):

- `calkit`, `"Calkit project"`, `metadata.description:calkit` (5 records)
- file-name queries (`"calkit.yaml"`, `filename:calkit.yaml`,
  `files.key:calkit.yaml`, `_files.key:...`, `files.entries.key:...`)
  return 0: Calkit archives upload `archive.zip` + `README.md`, and
  contents of zips are not indexed. Calkit-made archives are findable by
  the description text "This is an archive of release '...' from the
  Calkit project '...'".
- follow-ups: `creators.name:"McCabe, Rebecca"`, `Bachant`, `OpenFLASH`,
  `diazoDB`, `MDOcean`,
  `metadata.related_identifiers.identifier:"https://github.com/OWNER/REPO"`

CaltechDATA (`https://data.caltech.edu/api/records?q=...`; requires a
User-Agent header or returns 403): `calkit`, `"Calkit project"`,
`Bachant`, `boom-astro` (1 record, latest version only).

figshare (`POST https://api.figshare.com/v2/articles/search`,
`{"search_for": "calkit"}`): 0 hits (quoted `"calkit.yaml"` returns
unrelated noise).

OSF (`/v2/nodes/?filter[title|description][icontains]=calkit`), Dryad
(`/api/v2/search?q=calkit`), Software Heritage
(`/api/1/origin/search/calkit/`): no Calkit projects.

Other: arXiv API for 2511.00164 (no journal ref);
`search/issues` in `openjournals/joss-reviews` for OpenFLASH/MDOcean.

## Notes column tags

- `[shipped]`: publication built/archived from the Calkit project
- `[retroactive]`: publication predates Calkit; project converted later
- `[reproduction]`: Pete's Calkit reproduction of a third-party paper
- `[third-party adoption]`: external authors used Calkit, but not as the
  paper's build system

`is_pete` is true for repos owned by petebachant, calkit, or pwbachant, plus
repos where Pete is the primary contributor (XFlow-Energy/xfo,
swarm-migration/engie-hangest, UNH-CORE/RVAT-Re-dep).

Raw responses are in `raw/`; scripts in `scripts/` (`build_csv.py` holds the
manual publication annotations).
