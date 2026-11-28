"""Read a project at human speed, charging simulated time against a budget.

Every look at the project goes through here so an agent auditor works under
the same limits as a person: reading costs time by the word, running a command
costs time to type and read, and the budget runs out.

Environment:
    HREAD_LOG: JSON Lines file to log each action to (required)
    HREAD_BUDGET_MIN: simulated minutes available (default 20)
"""

import json
import os
import subprocess
import sys
import time

WORDS_PER_MIN = 240
RUN_COST_S = 20
WROTE_COST_S = 600
# Reading code with comprehension, in lines per minute
CODE_LINES_PER_MIN = 25
CODE_EXTENSIONS = (".py", ".r", ".sh", ".ipynb", ".do", ".jl")
VIEW_COST_S = 30
LIST_COST_S = 5
GREP_COST_S = 15
PAGE_LINES = 60


def get_spent(log_path: str) -> float:
    """Get the simulated seconds spent so far."""
    if not os.path.exists(log_path):
        return 0.0
    with open(log_path) as f:
        return sum(json.loads(line)["cost_s"] for line in f if line.strip())


def charge(log_path: str, action: str, text: str, fixed_s: float) -> float:
    """Log an action and return its simulated cost in seconds."""
    words = len(text.split())
    cost = fixed_s + 60 * words / WORDS_PER_MIN
    entry = {
        "t": time.time(),
        "action": action,
        "words": words,
        "cost_s": round(cost, 1),
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return cost


def main() -> None:
    log_path = os.environ["HREAD_LOG"]
    budget_s = 60 * float(os.environ.get("HREAD_BUDGET_MIN", "15"))
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    spent = get_spent(log_path)
    if args[0] == "time":
        print(f"Spent {spent / 60:.1f} of {budget_s / 60:.0f} min")
        return
    if spent >= budget_s:
        print(
            f"Out of time ({budget_s / 60:.0f} min spent). Stop reading and "
            "give your verdict now, from what you've seen."
        )
        sys.exit(1)
    kind = args[0]
    fixed = 0.0
    if kind == "file":
        path = args[1]
        start = int(args[2]) if len(args) > 2 else 1
        n = int(args[3]) if len(args) > 3 else PAGE_LINES
        with open(path, errors="replace") as f:
            lines = f.readlines()
        chunk = lines[start - 1 : start - 1 + n]
        text = "".join(chunk)
        out = (
            f"--- {path} lines {start}-{start + len(chunk) - 1} "
            f"of {len(lines)} ---\n{text}"
        )
        # Code is read line by line, far slower than prose
        if path.lower().endswith(CODE_EXTENSIONS):
            fixed = 60 * len(chunk) / CODE_LINES_PER_MIN
            text = ""
    elif kind == "ls":
        path = args[1] if len(args) > 1 else "."
        text = "\n".join(sorted(os.listdir(path)))
        out, fixed = text, LIST_COST_S
    elif kind == "grep":
        cmd = ["grep", "-rn", args[1]] + (args[2:] or ["."])
        res = subprocess.run(cmd, capture_output=True, text=True)
        text = res.stdout[:20000]
        out, fixed = text, GREP_COST_S
    elif kind == "view":
        text = ""
        out = (
            f"Charged {VIEW_COST_S} s to look at {args[1]}; open it with your "
            "image viewer now."
        )
        fixed = VIEW_COST_S
    elif kind == "run":
        wrote = "--wrote" in args
        cmd = args[args.index("--") + 1 :]
        res = subprocess.run(cmd, capture_output=True, text=True)
        text = (res.stdout + res.stderr)[:40000]
        out = text
        fixed = WROTE_COST_S if wrote else RUN_COST_S
    else:
        sys.exit(f"Unknown command: {kind}")
    cost = charge(log_path, " ".join(args)[:300], text, fixed)
    print(out)
    left = budget_s - spent - cost
    print(f"[{cost:.0f} s; {max(left, 0) / 60:.1f} min left]")


if __name__ == "__main__":
    main()
