"""Record typed findings in astra.yaml, with each evidence's source commit.

Stands in for the agent writing findings by hand after reading the
materialized outputs. The claims are taken as typed from a YAML file; only
source_commit (the commit that last produced each artifact in the named
universe) and created_at are filled in. Findings already in the spec keep
their created_at.
"""

import subprocess
import sys
from datetime import datetime, timezone

import yaml

FORMATS = {"analysis_data": "csv", "model_results": "json", "score_by_week": "png"}


def main() -> None:
    spec_path, typed_path = sys.argv[1:3]
    with open(spec_path) as f:
        text = f.read()
    spec = yaml.safe_load(text)
    existing = spec.get("findings") or {}
    with open(typed_path) as f:
        typed = yaml.safe_load(f)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    findings = {}
    for fid, finding in typed.items():
        evidence = []
        for ev in finding["evidence"]:
            universe = ev.pop("universe")
            path = f"results/{universe}/{ev['artifact']}.{FORMATS[ev['artifact']]}"
            ev["source_commit"] = subprocess.run(
                ["git", "log", "-1", "--format=%H", "--", path],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            evidence.append(ev)
        created_at = existing.get(fid, {}).get("created_at", now)
        findings[fid] = {
            "label": finding["label"],
            "claim": finding["claim"],
            "created_at": str(created_at),
            "scope": finding["scope"],
            "evidence": evidence,
        }
    if "\nfindings:" in text:
        text = text[: text.index("\nfindings:")]
    text = text.rstrip() + "\n\n" + yaml.safe_dump(
        {"findings": findings}, sort_keys=False, width=79, allow_unicode=True
    )
    with open(spec_path, "w") as f:
        f.write(text)


if __name__ == "__main__":
    main()
