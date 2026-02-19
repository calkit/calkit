#!/usr/bin/env python3
"""Sync documentation content from docs/ into README.md.

This script includes content from docs/installation.md and docs/quickstart.md
into README.md, excluding the top heading of each doc file.
"""

import re
import sys
from pathlib import Path
from typing import Match


def get_content_without_title(doc_path: Path) -> str:
    """Read a markdown file and return content without the top heading.

    Parameters
    ----------
    doc_path : Path
        Path to the markdown file

    Returns
    -------
    str
        Content with first heading removed
    """
    if not doc_path.exists():
        raise FileNotFoundError(f"File not found: {doc_path}")
    content = doc_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    # Skip the first heading
    for i, line in enumerate(lines):
        if line.startswith("#"):
            # Return everything after the first heading, trimmed
            return "\n".join(lines[i + 1 :]).strip()
    # If no heading found, return everything
    return content.strip()


def convert_relative_links(content: str) -> str:
    """Convert relative markdown links to absolute URLs for docs.calkit.org.

    Converts links like [text](relative-path.md) to [text](https://docs.calkit.org/relative-path)
    but only if they're not already absolute URLs or anchor links.

    Parameters
    ----------
    content : str
        Markdown content

    Returns
    -------
    str
        Content with converted links
    """
    # Match markdown links [text](url) where url doesn't start with http, https, #, or /
    pattern = r"\[([^\]]+)\]\((?!https?:|#|/)([^\)]+)\)"

    def replace_link(match: Match[str]) -> str:
        text = match.group(1)
        rel_url = match.group(2)
        # Remove trailing .md and /index.md for absolute URLs
        if rel_url.endswith("/index.md"):
            abs_url = f"https://docs.calkit.org/{rel_url[:-9]}"
        elif rel_url.endswith(".md"):
            abs_url = f"https://docs.calkit.org/{rel_url[:-3]}"
        else:
            abs_url = f"https://docs.calkit.org/{rel_url}"
        return f"[{text}]({abs_url})"

    return re.sub(pattern, replace_link, content)


def adjust_heading_levels(content: str, shift: int) -> str:
    """Adjust markdown heading levels by the specified amount.

    Parameters
    ----------
    content : str
        Markdown content
    shift : int
        Number of levels to shift (positive=increase, negative=decrease)

    Returns
    -------
    str
        Content with adjusted heading levels
    """
    if shift == 0:
        return content
    lines = content.split("\n")
    adjusted = []
    for line in lines:
        match = re.match(r"^(#+)(.+)$", line)
        if match:
            hashes = match.group(1)
            rest = match.group(2)
            new_level = max(1, len(hashes) + shift)
            adjusted.append("#" * new_level + rest)
        else:
            adjusted.append(line)
    return "\n".join(adjusted)


def process_readme(readme_path: Path, docs_dir: Path) -> str:
    """Process README.md and replace include sections with actual content.

    Include markers have the format:
    <!-- INCLUDE: docs/filename.md [+shift] -->
    ... current content ...
    <!-- END INCLUDE -->

    Where filename is relative to the docs directory, and optional +shift
    adjusts heading levels (e.g., +1 makes ## become ###).

    Parameters
    ----------
    readme_path : Path
        Path to README.md
    docs_dir : Path
        Path to docs directory

    Returns
    -------
    str
        Processed README content
    """
    content = readme_path.read_text(encoding="utf-8")
    # Find include blocks - format: <!-- INCLUDE: docs/file.md [+shift] -->...<!-- END INCLUDE -->
    pattern = r"<!-- INCLUDE: docs/([^\s\]]+)(?:\s\+(\d+))? -->(.*?)<!-- END INCLUDE -->"

    def replace_include(match: Match[str]) -> str:
        doc_file = match.group(1).strip()
        shift = int(match.group(2)) if match.group(2) else 0
        doc_path = docs_dir / doc_file
        try:
            doc_content = get_content_without_title(doc_path)
            if shift != 0:
                doc_content = adjust_heading_levels(doc_content, shift)
            # Convert relative links to absolute URLs
            doc_content = convert_relative_links(doc_content)
            # Return just the content, preserving the markers
            return f"<!-- INCLUDE: docs/{doc_file}{' +' + str(shift) if shift else ''} -->\n\n{doc_content}\n\n<!-- END INCLUDE -->"
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return match.group(0)

    return re.sub(pattern, replace_include, content, flags=re.DOTALL)


def main() -> None:
    """Main entry point."""
    repo_root = Path(__file__).parent.parent
    readme_path = repo_root / "README.md"
    docs_dir = repo_root / "docs"
    processed = process_readme(readme_path, docs_dir)
    readme_path.write_text(processed, encoding="utf-8")


if __name__ == "__main__":
    main()
