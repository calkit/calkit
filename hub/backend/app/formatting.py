"""Formatting code written in the browser.

A script saved from the figure editor is committed to the user's repo, so
it should look like code someone would write by hand: ruff's formatter,
at PEP 8's 79 columns, which is the convention across Calkit.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)

PYTHON_LINE_LENGTH = 79


def format_python(code: str) -> str:
    """The code as ruff formats it, or as given when it can't be parsed.

    Formatting is a courtesy, not a gate: a script with a syntax error is
    still the user's script, and refusing to save it would lose work over
    a missing bracket. ``--isolated`` keeps the hub's own ruff config out
    of the user's code.
    """
    try:
        result = subprocess.run(
            [
                "ruff",
                "format",
                "--isolated",
                "--line-length",
                str(PYTHON_LINE_LENGTH),
                "--stdin-filename",
                "script.py",
                "-",
            ],
            input=code,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"Could not run ruff: {e}")
        return code
    if result.returncode != 0:
        logger.info(f"Leaving script unformatted: {result.stderr.strip()}")
        return code
    return result.stdout
