"""Archive a batch of trials run before the benchmark moved here.

Copies each run's prompt, environment script, meta, transcript, agent stderr,
and agent seconds into runs/<batch>/<run>/, packs its project into
project.tgz the way bench/run_batch.py does (without environments or local
caches), and writes import.json with where it came from and the Calkit
commit its trial used, read from the snapshot path in its meta.

Template and agent commits made then carry this machine's global Git email,
which the transcripts show in `git log` output; it's replaced with the
builder's in the archived copies, and import.json counts the replacements.
The projects' Git objects are archived as they are.

Usage: python bench/import_batch.py <source dir> <batch>
"""

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

import archive
import arms

ROOT = arms.ROOT
FILES = [
    "prompt.txt",
    "env.sh",
    "meta.json",
    "transcript.jsonl",
    "agent-stderr.txt",
    "agent-seconds.txt",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("batch")
    args = parser.parse_args()
    email = subprocess.run(
        ["git", "config", "--global", "user.email"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert email
    out = ROOT / "runs" / args.batch
    if out.exists():
        shutil.rmtree(out)
    runs = sorted(
        p for p in args.source.iterdir() if (p / "meta.json").exists()
    )
    for src in runs:
        dest = out / src.name
        dest.mkdir(parents=True)
        n_replaced = 0
        for name in FILES:
            text = (src / name).read_text()
            n_replaced += text.count(email)
            (dest / name).write_text(text.replace(email, arms.BUILDER[1]))
        archive.pack(
            src / "project", dest / "project.tgz", skip=archive.skip_run_path
        )
        meta = json.loads((src / "meta.json").read_text())
        calkit_rev = None
        if meta["arm"] == "calkit":
            match = re.search(
                r"calkit-([0-9a-f]{7,40})/bin/calkit", meta["calkit_command"]
            )
            assert match, meta["calkit_command"]
            short = match.group(1)
            calkit_rev = subprocess.run(
                ["git", "rev-parse", "--verify", f"{short}^{{commit}}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        record = {
            "source": str(src),
            "calkit_rev": calkit_rev,
            "n_email_replacements": n_replaced,
        }
        (dest / "import.json").write_text(json.dumps(record, indent=2) + "\n")
        print(src.name, n_replaced)
    print(f"Archived {len(runs)} runs into {out}")


if __name__ == "__main__":
    main()
