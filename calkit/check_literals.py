"""Functions to check for untraceable numeric literals in LaTeX sources."""

from __future__ import annotations

import re
from typing import Any


def _mask_match(match: re.Match) -> str:
    """Return whitespace of the same length as the matched string.
    This preserves line and column numbers while removing the content from matching.
    """
    return " " * len(match.group(0))


def _mask_exclusion_zones(tex_source: str) -> str:
    """Mask out LaTeX constructs where numeric literals should be ignored."""
    masked = tex_source

    # Mask comments: % until end of line (but ignore escaped \%)
    # Using a negative lookbehind to avoid matching \%
    masked = re.sub(r"(?<!\\)%.*$", _mask_match, masked, flags=re.MULTILINE)

    # Mask specific environments
    environments_to_mask = ["thebibliography"]
    for env in environments_to_mask:
        # Match \begin{env} ... \end{env} across multiple lines
        pattern = (
            r"\\begin\{"
            + re.escape(env)
            + r"\}.*?\\end\{"
            + re.escape(env)
            + r"\}"
        )
        masked = re.sub(pattern, _mask_match, masked, flags=re.DOTALL)

    # Mask specific macros
    macros_to_mask = [
        r"\\cite[a-zA-Z]*\*?\{[^}]*\}",
        r"\\bibitem\{[^}]*\}",
        r"\\href\{[^}]*\}\{[^}]*\}",
        r"\\url\{[^}]*\}",
        r"\\doi\{[^}]*\}",
        r"\\ref\{[^}]*\}",
        r"\\eqref\{[^}]*\}",
        r"\\pageref\{[^}]*\}",
        r"\\label\{[^}]*\}",
        r"\\input\{[^}]*\}",
        r"\\include\{[^}]*\}",
        r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}",
        r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\}",
        r"\\setlength\{[^}]*\}\{[^}]*\}",
        r"\\vspace\*?\{[^}]*\}",
        r"\\hspace\*?\{[^}]*\}",
        r"\\geometry\{[^}]*\}",
        r"\\multicolumn\{[^}]*\}\{[^}]*\}\{[^}]*\}",
    ]
    for macro_pattern in macros_to_mask:
        masked = re.sub(macro_pattern, _mask_match, masked, flags=re.DOTALL)

    # Mask bare DOIs
    masked = re.sub(r"10\.\d{4,}/[^\s]+", _mask_match, masked)

    # Mask years (1500-2100)
    masked = re.sub(r"\b(1[5-9]\d{2}|20\d{2}|2100)\b", _mask_match, masked)

    # Mask page ranges (e.g. 123--145, pp. 123)
    masked = re.sub(r"\b\d+\s*--\s*\d+\b", _mask_match, masked)
    masked = re.sub(r"\bpp\.\s*\d+\b", _mask_match, masked)

    return masked


def find_untraceable_literals(
    tex_source: str,
    filepath: str,
    from_json_values: set[str] | dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """Scan LaTeX source for hardcoded numeric literals not traceable to a pipeline output.

    Parameters
    ----------
    tex_source : str
        The contents of the LaTeX file to scan.
    filepath : str
        The path of the LaTeX file (used for reporting).
    from_json_values : set[str] | dict[str, str] | None
        Traceable string values (or dict mapping value to macro name) that the pipeline produces.
        Any matched literal corresponding to one of these values will not be flagged.

    Returns
    -------
    list[dict[str, Any]]
        A list of findings. Each finding is a dictionary with keys:
        - value: the matched literal string
        - file: the filepath
        - line: 1-indexed line number
        - column: 1-indexed column number
        - context: the surrounding text snippet
        - reason: explanation of why it was flagged
        - suggestion: fix instructions
    """
    from_json: dict[str, str | None]
    if from_json_values is None:
        from_json = {}
    elif isinstance(from_json_values, set):
        from_json = {v: None for v in from_json_values}
    else:
        from_json = from_json_values

    findings = []
    masked_source = _mask_exclusion_zones(tex_source)

    # Regex patterns for result-like values
    # Group 1 captures the full matched literal
    result_like_patterns = [
        # Values with uncertainty (e.g., 0.42 \pm 0.03)
        r"(\b\d+(?:\.\d+)?\s*\\pm\s*\d+(?:\.\d+)?\b)",
        # Scientific notation (e.g., 1.2e-3, 1.2\times10^{-3})
        r"(\b\d+(?:\.\d+)?(?:[eE][+-]?\d+|\s*\\times\s*10\^\{?[+-]?\d+\}?)(?!\d))",
        # Percentages (e.g., 12.7\%)
        r"(\b\d+(?:\.\d+)?\s*\\%)",
        # Decimals (e.g., 0.42) - only match if not part of a larger word
        r"(\b\d+\.\d+\b)",
    ]

    # Combine patterns with OR. We must use non-capturing groups for internal structure
    # if we combine them, or just search them one by one. To avoid overlapping matches,
    # we'll search one by one and keep track of matched indices.

    matched_intervals: list[tuple[int, int]] = []

    def is_overlapping(start: int, end: int) -> bool:
        for s, e in matched_intervals:
            if max(start, s) < min(end, e):
                return True
        return False

    lines = tex_source.splitlines()

    for pattern in result_like_patterns:
        for match in re.finditer(pattern, masked_source):
            start, end = match.span(1)
            if is_overlapping(start, end):
                continue

            matched_intervals.append((start, end))
            matched_str = match.group(1).strip()

            # Check if this literal is traceable
            # We strip trailing/leading whitespace and standardize some formatting for comparison
            cmp_str = matched_str.replace(" ", "")
            traceable = False
            macro_name = None

            for tracked_val, mac_name in from_json.items():
                if cmp_str == tracked_val.replace(" ", ""):
                    traceable = True
                    macro_name = mac_name
                    break

            if traceable:
                continue

            # Calculate line and column
            preceding = tex_source[:start]
            line_idx = preceding.count("\n")
            col_idx = (
                len(preceding) - preceding.rfind("\n") - 1
                if "\n" in preceding
                else len(preceding)
            )

            # Get context (the line where the match occurred)
            context = lines[line_idx].strip() if line_idx < len(lines) else ""

            suggestion = (
                "Compute the value in a stage, emit it to JSON, run it through "
                "a `calkit latex from-json` stage, and reference the generated macro "
                "instead of hardcoding."
            )
            if macro_name:
                # If we couldn't precisely match it but somehow we know the macro (fallback logic if added later)
                suggestion += f" Consider using \\{macro_name}."

            finding = {
                "value": matched_str,
                "file": filepath,
                "line": line_idx + 1,
                "column": col_idx + 1,
                "context": context,
                "reason": "result-like decimal not traceable to a pipeline output",
                "suggestion": suggestion,
            }
            findings.append(finding)

    # Sort findings by line and column
    findings.sort(key=lambda x: (x["line"], x["column"]))

    return findings
