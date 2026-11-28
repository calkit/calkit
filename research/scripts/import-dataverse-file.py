"""Download one file of a Dataverse dataset at a pinned version.

The file's checksum, as Dataverse reports it for that version, is verified
before anything is written, and the version's license and release time are
saved beside it, so where the copy came from and on what terms is recorded
with it.
"""

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--server", default="https://dataverse.harvard.edu")
parser.add_argument("--doi", required=True, help="e.g., 10.7910/DVN/TVJCTX")
parser.add_argument("--version", required=True, help="e.g., 1.0")
parser.add_argument("--file-id", required=True, type=int)
parser.add_argument("--output", required=True, help="Path to save it at.")
parser.add_argument(
    "--metadata-output", required=True, help="JSON to save its record in."
)
args = parser.parse_args()
# Dataverse refuses urllib's default user agent
headers = {"User-Agent": "calkit"}
# What Dataverse says that version holds
query = urllib.parse.urlencode({"persistentId": f"doi:{args.doi}"})
url = (
    f"{args.server}/api/datasets/:persistentId/versions/{args.version}?{query}"
)
with urllib.request.urlopen(
    urllib.request.Request(url, headers=headers)
) as resp:
    version = json.load(resp)["data"]
data_files = [
    f["dataFile"]
    for f in version["files"]
    if f["dataFile"]["id"] == args.file_id
]
if not data_files:
    raise SystemExit(
        f"File {args.file_id} is not in version {args.version} of {args.doi}"
    )
data_file = data_files[0]
checksum = data_file["checksum"]
# Download and verify it before writing
url = f"{args.server}/api/access/datafile/{args.file_id}"
with urllib.request.urlopen(
    urllib.request.Request(url, headers=headers)
) as resp:
    content = resp.read()
algorithm = checksum["type"].lower().replace("-", "")
digest = hashlib.new(algorithm, content).hexdigest()
if digest != checksum["value"]:
    raise SystemExit(
        f"{checksum['type']} of {data_file['filename']} is {digest}, but "
        f"Dataverse reports {checksum['value']}"
    )
Path(args.output).parent.mkdir(parents=True, exist_ok=True)
Path(args.output).write_bytes(content)
record = {
    "doi": args.doi,
    "version": args.version,
    "release_time": version["releaseTime"],
    "license": version.get("license"),
    "terms_of_use": version.get("termsOfUse"),
    "file_id": args.file_id,
    "filename": data_file["filename"],
    "size_bytes": len(content),
    "checksum": checksum,
}
with open(args.metadata_output, "w") as f:
    json.dump(record, f, indent=2)
    f.write("\n")
