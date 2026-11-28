"""Print the run id from `orx exp status --json` output."""

import json
import sys

with open(sys.argv[1]) as f:
    print(json.load(f)["runId"])
