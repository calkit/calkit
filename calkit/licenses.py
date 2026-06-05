"""Functionality for working with licenses.

Calkit projects will often include code, data, text, and other content
and artifacts that may each have their own license.
"""

from __future__ import annotations

import os
import re

# A list of (SPDX license ID, required substring groups) used to detect
# licenses from the text of a license file.
# Each entry maps an SPDX ID to a list of "all-of" groups; the license
# matches if *every* group has at least one of its substrings present in the
# (lowercased, whitespace-normalized) license text.
# This is intentionally tolerant so that licenses written by hand, generated
# by GitHub, or produced by Calkit's own templates are all detected.
# A single license file may contain more than one license (e.g., Calkit's
# default dual MIT/CC-BY-4.0 license), so all matching IDs are returned.
_LICENSE_MARKERS: list[tuple[str, list[list[str]]]] = [
    (
        "mit",
        [
            [
                "mit license",
                "permission is hereby granted, free of charge, to any "
                "person obtaining a copy",
            ]
        ],
    ),
    (
        "apache-2.0",
        [["apache license"], ["version 2.0", "version 2,"]],
    ),
    (
        "bsd-3-clause",
        [
            ["redistribution and use in source and binary forms"],
            ["neither the name of"],
        ],
    ),
    (
        "bsd-2-clause",
        [
            ["redistribution and use in source and binary forms"],
        ],
    ),
    (
        "gpl-3.0",
        [["gnu general public license"], ["version 3"]],
    ),
    (
        "gpl-2.0",
        [["gnu general public license"], ["version 2"]],
    ),
    (
        "lgpl-3.0",
        [["gnu lesser general public license"], ["version 3"]],
    ),
    (
        "agpl-3.0",
        [["gnu affero general public license"], ["version 3"]],
    ),
    (
        "mpl-2.0",
        [["mozilla public license"], ["version 2.0", "version 2,"]],
    ),
    (
        "cc-by-4.0",
        [
            [
                "creative commons attribution 4.0",
                "cc by 4.0",
                "cc-by-4.0",
                "creativecommons.org/licenses/by/4.0",
            ]
        ],
    ),
    (
        "cc0-1.0",
        [
            [
                "cc0 1.0",
                "creative commons zero",
                "creativecommons.org/publicdomain/zero/1.0",
            ]
        ],
    ),
    (
        "isc",
        [
            [
                "isc license",
                "permission to use, copy, modify, and/or distribute this "
                "software",
            ]
        ],
    ),
    (
        "unlicense",
        [
            [
                "this is free and unencumbered software released into the "
                "public domain"
            ]
        ],
    ),
]

# Candidate file names to search for a project license, in priority order.
LICENSE_FILE_CANDIDATES = [
    "LICENSE",
    "LICENSE.txt",
    "LICENSE.md",
    "LICENSE.rst",
    "LICENCE",
    "LICENCE.txt",
    "LICENCE.md",
    "COPYING",
]


def detect_license_ids(text: str) -> list[str]:
    """Detect SPDX license IDs present in license text.

    The match is tolerant of whitespace and case, and a single body of text
    can match multiple licenses (e.g., a dual-licensed project).
    Returns the IDs in a deterministic order with duplicates removed.
    """
    if not text:
        return []
    # Lowercase and collapse all runs of whitespace so that line wrapping in
    # the source license file does not break multi-word substring matches
    normalized = re.sub(r"\s+", " ", text.lower())
    found: list[str] = []
    for license_id, groups in _LICENSE_MARKERS:
        # The "bsd-3-clause" and "bsd-2-clause" markers overlap; only report
        # the 2-clause variant when the 3-clause variant did not match
        if license_id == "bsd-2-clause" and "bsd-3-clause" in found:
            continue
        if all(
            any(substring in normalized for substring in group)
            for group in groups
        ):
            found.append(license_id)
    return found


def find_license_file(wdir: str | None = None) -> str | None:
    """Return the path to the project license file, if one exists."""
    for candidate in LICENSE_FILE_CANDIDATES:
        path = candidate if wdir is None else os.path.join(wdir, candidate)
        if os.path.isfile(path):
            return path
    return None


LICENSE_TEMPLATE_DUAL = """
This project is licensed under a dual-license structure to appropriately cover
both the software code and the non-code content (data, text, figures, etc.).

Source code (MIT License)

All source code contained within this repository, including but not limited to
files with the extensions .js, .py, .html, .css, .ts, .jsx, .tsx, shell
scripts, build configurations, and their related files, is licensed under
the MIT License.

The MIT License (MIT)

Copyright (c) {year} {copyright_holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Content, data, and documentation (CC BY 4.0)

All non-code assets, including but not limited to prose, documentation, data,
figures, images, designs, and text written in Markdown or similar formats
(e.g., files in a docs/ directory, this LICENSE file itself, or .txt files
containing prose or data), are licensed under the Creative Commons Attribution
4.0 International Public License (CC BY 4.0).

To view a copy of this license, visit:

CC BY 4.0 Deed (summary):
https://creativecommons.org/licenses/by/4.0/

CC BY 4.0 Legal Code (full license):
https://creativecommons.org/licenses/by/4.0/legalcode

This license requires you to give appropriate credit, provide a link to the
license, and indicate if changes were made. You may do so in any reasonable
manner, but not in any way that suggests the licensor endorses you or your use.
""".strip()
