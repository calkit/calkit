#!/usr/bin/env python3
"""Generate calkit/resources/devcontainer/devcontainer.json.

The dev container's VS Code customizations are derived from the shared VS Code
config in calkit/resources/vscode, so the settings a project gets from
``calkit update vscode-config`` and the ones it gets inside a container can't
drift apart. Edit calkit/resources/vscode/*.json or
calkit/resources/devcontainer/base.json, then run this
(``make sync-resources``, or just ``make format``).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from calkit.resources import (  # noqa: E402
    DEVCONTAINER_FNAME,
    get_dir,
    render_devcontainer_spec,
)


def main() -> int:
    out_path = Path(get_dir()) / "devcontainer" / DEVCONTAINER_FNAME
    spec = render_devcontainer_spec()
    out_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
