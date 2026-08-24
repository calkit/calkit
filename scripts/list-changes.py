#!/usr/bin/env python3
"""List each product's commits since its last release, i.e., what's due.

The repo ships several products on independent release cadences, each with
its own tag namespace and its own slice of the tree. Since a release is cut
by tagging, "what's unreleased" is the commits touching a product's paths
since its newest tag. Run with ``make changes``.

The product definitions mirror the ``if:`` conditions on the publish
workflows in .github/workflows, which are what actually decide whether a
given tag publishes a given product. Keep them in sync.
"""

import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class Product:
    name: str
    # Glob for ``git tag --list``, matching this product's tags only
    tag_glob: str
    # Paths whose changes belong to this product, as git pathspecs
    paths: list[str] = field(default_factory=lambda: ["."])
    note: str = ""


# The CLI's tags carry no prefix, and it owns everything that isn't one of
# the separately released subprojects; the JupyterLab extension ships inside
# the Python package rather than on its own, so it counts as part of the CLI.
OTHER_PRODUCT_DIRS = ["hub", "vscode-ext", "browser-ext"]

PRODUCTS = [
    Product(
        name="calkit (Python package)",
        tag_glob="v*",
        paths=["."] + [f":(exclude){d}" for d in OTHER_PRODUCT_DIRS],
        note="includes the JupyterLab extension",
    ),
    Product(name="hub", tag_glob="hub/v*", paths=["hub"]),
    Product(name="vscode-ext", tag_glob="vscode-ext/v*", paths=["vscode-ext"]),
    Product(
        name="browser-ext", tag_glob="browser-ext/v*", paths=["browser-ext"]
    ),
]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def latest_tag(glob: str) -> str | None:
    # Sort by version rather than lexically, so v0.42.1 beats v0.9.4
    tags = [
        t
        for t in git("tag", "--list", glob, "--sort=-v:refname").split("\n")
        if t
    ]
    # git's tag globs aren't path-aware: '*' matches '/' too, so a bare 'v*'
    # also picks up 'vscode-ext/v0.1.6'. An unprefixed glob means unprefixed
    # tags only.
    if "/" not in glob:
        tags = [t for t in tags if "/" not in t]
    return tags[0] if tags else None


def main() -> int:
    head = git("rev-parse", "--short", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    print(f"Unreleased commits as of {head} ({branch})\n")
    due = []
    for product in PRODUCTS:
        tag = latest_tag(product.tag_glob)
        heading = product.name
        if product.note:
            heading += f" — {product.note}"
        print(heading)
        if tag is None:
            # Never released, so every commit touching it is unreleased
            rev_range = "HEAD"
            print(f"  Never released (no {product.tag_glob} tag)")
        else:
            rev_range = f"{tag}..HEAD"
            date = git("log", "-1", "--format=%ad", "--date=short", tag)
            print(f"  Last release: {tag} ({date})")
        log = git(
            "log",
            "--format=%h %s",
            "--no-merges",
            rev_range,
            "--",
            *product.paths,
        )
        commits = [line for line in log.split("\n") if line]
        if not commits:
            print("  Up to date\n")
            continue
        due.append((product.name, len(commits)))
        print(f"  {len(commits)} unreleased commit(s):")
        for line in commits:
            print(f"    {line}")
        print()
    if due:
        summary = ", ".join(f"{name} ({n})" for name, n in due)
        print(f"Releases due: {summary}")
    else:
        print("Releases due: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
