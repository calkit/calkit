"""Windows-specific functionality."""

from __future__ import annotations

import re
import sys

SMART_APP_CONTROL_DOCS_URL = (
    "https://docs.calkit.org/installation/#windows-smart-app-control"
)
# STATUS_SYSTEM_INTEGRITY_POLICY_VIOLATION, what a process exits with when
# Windows won't load it or one of its DLLs
APP_CONTROL_BLOCK_STATUS = 0xC0E90002
# How a block shows in output: the message for error 4551, e.g., in a Python
# ImportError, or the status above, as uv shows it or as a signed or unsigned
# exit code
APP_CONTROL_BLOCK_REGEX = re.compile(
    r"Application Control policy has blocked"
    r"|0xc0e90002|\b3236495362\b|-1058471934\b",
    re.IGNORECASE,
)


def smart_app_control_on() -> bool:
    """True when Windows Smart App Control is enforcing, so it may block
    unsigned executables and DLLs, e.g., those environments install.
    """
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\CI\Policy",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(
                key, "VerifiedAndReputablePolicyState"
            )
    except OSError:
        return False
    # 0 is off, and 2 only evaluates, without blocking anything
    return bool(value == 1)


def app_control_blocked(
    output: str = "", returncode: int | None = None
) -> bool:
    """True when output or an exit code shows that Windows App Control, e.g.,
    Smart App Control, blocked a file from running.
    """
    if (
        returncode is not None
        and returncode % 2**32 == APP_CONTROL_BLOCK_STATUS
    ):
        return True
    return APP_CONTROL_BLOCK_REGEX.search(output) is not None
