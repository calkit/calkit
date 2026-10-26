"""Total up the budget for the 2027 pilot.

The line items are data in docs/one-pager/2027-budget.csv, so the total and
its parts, which the one-pager quotes, are computed here rather than typed,
and can't disagree with each other.

Writes results/2027-budget.json.
"""

import argparse
import csv
import json
from typing import Any

parser = argparse.ArgumentParser()
parser.add_argument("--workshops", type=int, required=True)
parser.add_argument("--attendees", type=int, required=True)
parser.add_argument("--supported", type=int, required=True)
# Overhead taken by whoever receives the money, e.g., an institution's
# indirect costs or a fiscal sponsor's fee, as a fraction of direct costs
parser.add_argument("--indirect-rate", type=float, default=0.0)
args = parser.parse_args()
with open("docs/one-pager/2027-budget.csv", encoding="utf-8") as f:
    rows: list[dict[str, Any]] = list(csv.DictReader(f))
items = [
    row
    | {
        "quantity": float(row["quantity"]),
        "unit_cost": float(row["unit_cost"]),
        "cost": float(row["quantity"]) * float(row["unit_cost"]),
    }
    for row in rows
]
by_category: dict[str, float] = {}
for item in items:
    by_category[item["category"]] = (
        by_category.get(item["category"], 0.0) + item["cost"]
    )
direct = sum(by_category.values())
indirect = direct * args.indirect_rate
total = direct + indirect
trained = args.workshops * args.attendees
results = {
    "items": items,
    "by_category": by_category,
    "direct_total": direct,
    "indirect_rate": args.indirect_rate,
    "indirect": indirect,
    "total": total,
    "workshops": args.workshops,
    "researchers_trained": trained,
    "projects_supported": args.supported,
    "cost_per_researcher": total / trained,
}
with open("results/2027-budget.json", "w") as f:
    json.dump(results, f, indent=2)
    f.write("\n")
