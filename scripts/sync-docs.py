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
    """Convert relative links and image URLs to absolute docs URLs.

    Converts markdown links, markdown images, and HTML img src values to
    docs.calkit.org URLs when they are not already absolute.

    Parameters
    ----------
    content : str
        Markdown content

    Returns
    -------
    str
        Content with converted links
    """

    def to_docs_url(url: str, is_markdown_doc_link: bool = False) -> str:
        if re.match(r"^(https?:|mailto:|#)", url):
            return url
        if url.startswith("/"):
            return f"https://docs.calkit.org{url}"
        if is_markdown_doc_link and url.endswith("/index.md"):
            return f"https://docs.calkit.org/{url[:-9]}"
        if is_markdown_doc_link and url.endswith(".md"):
            return f"https://docs.calkit.org/{url[:-3]}"
        return f"https://docs.calkit.org/{url}"

    def to_readme_image_url(url: str) -> str:
        if re.match(r"^(https?:|mailto:|#)", url):
            return url
        if url.startswith("/docs/img/"):
            return url[1:]
        if url.startswith("docs/img/"):
            return url
        if url.startswith("/img/"):
            return f"docs/{url[1:]}"
        if url.startswith("img/"):
            return f"docs/{url}"
        return url

    # Match markdown links [text](url) where url doesn't start with http,
    # https, #, or /
    link_pattern = r"\[([^\]]+)\]\((?!https?:|mailto:|#|/)([^\)]+)\)"

    def replace_link(match: Match[str]) -> str:
        text = match.group(1)
        rel_url = match.group(2).strip()
        abs_url = to_docs_url(rel_url, is_markdown_doc_link=True)
        return f"[{text}]({abs_url})"

    content = re.sub(link_pattern, replace_link, content)

    # Match markdown images ![alt](url)
    image_pattern = r"!\[([^\]]*)\]\(([^\)]+)\)"

    def replace_image(match: Match[str]) -> str:
        alt_text = match.group(1)
        image_url = match.group(2).strip()
        return f"![{alt_text}]({to_readme_image_url(image_url)})"

    content = re.sub(image_pattern, replace_image, content)

    # Match HTML image tags and convert src values.
    html_image_pattern = r'(<img\b[^>]*\bsrc=["\'])([^"\']+)(["\'])'

    def replace_html_image_src(match: Match[str]) -> str:
        before = match.group(1)
        src = match.group(2).strip()
        after = match.group(3)
        return f"{before}{to_readme_image_url(src)}{after}"

    return re.sub(html_image_pattern, replace_html_image_src, content)


ADMONITION_TYPES = {
    "note": "NOTE",
    "info": "NOTE",
    "tip": "TIP",
    "important": "IMPORTANT",
    "warning": "WARNING",
    "danger": "CAUTION",
    "caution": "CAUTION",
}


def convert_admonitions(content: str) -> str:
    """Convert MkDocs admonitions into GitHub alerts.

    MkDocs (Python-Markdown) admonitions like::

        !!! note "Optional title"
            Body text.

    render as literal text on GitHub, so they are rewritten as GitHub
    alerts, e.g., ``> [!NOTE]``. Unrecognized admonition types are left
    alone. Each alert is emitted with a ``<!-- prettier-ignore -->``
    comment, since prettier otherwise reflows the ``> [!NOTE]`` marker onto
    the following line and breaks the alert.

    Parameters
    ----------
    content : str
        Markdown content

    Returns
    -------
    str
        Content with admonitions converted
    """
    lines = content.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        match = re.match(r'^!!!\s+(\w+)\s*(?:"([^"]*)")?\s*$', lines[i])
        if match is None:
            out.append(lines[i])
            i += 1
            continue
        kind = ADMONITION_TYPES.get(match.group(1).lower())
        if kind is None:
            out.append(lines[i])
            i += 1
            continue
        # Collect the indented body, keeping blank lines that are followed
        # by more body
        i += 1
        body: list[str] = []
        while i < len(lines):
            line = lines[i]
            if line.strip() == "":
                body.append("")
                i += 1
                continue
            if not line.startswith((" ", "\t")):
                break
            body.append(line)
            i += 1
        while body and body[-1] == "":
            body.pop()
            i -= 1
        # Strip the common indentation from the body
        indents = [
            len(line) - len(line.lstrip()) for line in body if line.strip()
        ]
        dedent = min(indents) if indents else 0
        # Keep the alert adjacent to its own prettier-ignore comment,
        # dropping any blank line the MkDocs source had in between
        while out and out[-1].strip() == "":
            out.pop()
        if not out or out[-1].strip() != "<!-- prettier-ignore -->":
            if out:
                out.append("")
            out.append("<!-- prettier-ignore -->")
        out.append(f"> [!{kind}]")
        title = match.group(2)
        if title:
            out.append(f"> **{title}**")
            out.append(">")
        for line in body:
            out.append(">" if line == "" else f"> {line[dedent:]}")
    return "\n".join(out)


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
    # Find include blocks - format: <!-- INCLUDE: docs/file.md [+shift]
    # -->...<!-- END INCLUDE -->
    pattern = (
        r"<!-- INCLUDE: docs/([^\s\]]+)(?:\s\+(\d+))? "
        r"-->(.*?)<!-- END INCLUDE -->"
    )

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
            # Convert MkDocs admonitions into GitHub alerts
            doc_content = convert_admonitions(doc_content)
            # Return just the content, preserving the markers
            return (
                f"<!-- INCLUDE: docs/{doc_file}"
                f"{' +' + str(shift) if shift else ''} "
                f"-->\n\n{doc_content}\n\n<!-- END INCLUDE -->"
            )
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
