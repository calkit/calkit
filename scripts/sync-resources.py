#!/usr/bin/env python3
"""Generate the derived files under calkit/resources.

Two things get generated here, both so a single source of truth stays
editable where it makes sense to read it:

- The dev container's VS Code customizations come from the shared VS Code
  config in calkit/resources/vscode, so the settings a project gets from
  ``calkit update vscode-config`` and the ones it gets inside a container
  can't drift apart.
- The example workflow is bundled from actions/run/example.yml, which lives
  next to
  the action it calls, but has to ship inside the package for
  ``calkit update github-actions`` to install it without a download. The same
  file fills in the snippet in actions/run/README.md.

Edit the sources, then run this (``make sync-resources``, or just
``make format``).
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from calkit.resources import (  # noqa: E402
    DEVCONTAINER_FNAME,
    GITHUB_ACTIONS_FNAME,
    get_dir,
    render_devcontainer_spec,
)

SNIPPET_START = "<!-- snippet:example.yml:start -->"
SNIPPET_END = "<!-- snippet:example.yml:end -->"


def main() -> int:
    repo_dir = Path(__file__).parent.parent
    resources_dir = Path(get_dir())
    out_path = resources_dir / "devcontainer" / DEVCONTAINER_FNAME
    spec = render_devcontainer_spec()
    out_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    workflow_path = repo_dir / "actions" / "run" / GITHUB_ACTIONS_FNAME
    workflow_out = resources_dir / "github-actions" / GITHUB_ACTIONS_FNAME
    workflow_out.parent.mkdir(exist_ok=True)
    shutil.copyfile(workflow_path, workflow_out)
    print(f"Wrote {workflow_out}")
    # Fill in the workflow snippet in the action's README
    readme_path = repo_dir / "actions" / "run" / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    start = readme.index(SNIPPET_START)
    end = readme.index(SNIPPET_END, start)
    workflow = workflow_path.read_text(encoding="utf-8").rstrip()
    snippet = f"{SNIPPET_START}\n\n```yaml\n{workflow}\n```\n\n"
    readme = readme[:start] + snippet + readme[end:]
    readme_path.write_text(readme, encoding="utf-8")
    print(f"Wrote {readme_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
