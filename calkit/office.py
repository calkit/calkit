"""Functionality for working with Microsoft Office."""

import os
import sys

# Each app's executable, which it registers the path of on Windows, and
# its app bundle's name on macOS
OFFICE_APPS = {
    "word": ("Winword.exe", "Microsoft Word"),
    "excel": ("excel.exe", "Microsoft Excel"),
    "powerpoint": ("powerpnt.exe", "Microsoft PowerPoint"),
}


def app_installed(app: str) -> bool:
    """Whether an Office app, e.g., Word, is installed."""
    return find_app_path(app) is not None


def find_app_path(app: str) -> str | None:
    """Where an Office app, e.g., Word, is installed: its macOS bundle, or
    on Windows the executable it registers the path of, else the one in an
    install directory.
    """
    exe, bundle = OFFICE_APPS[app]
    if sys.platform == "darwin":
        for d in ("/Applications", "~/Applications"):
            path = os.path.expanduser(f"{d}/{bundle}.app")
            if os.path.isdir(path):
                return path
        return None
    if sys.platform != "win32":
        return None
    import winreg

    # Machine-wide, in either registry view, since 32-bit Office registers
    # in the 32-bit one, else for this user, as Office installs either way
    for hive, view in (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ):
        try:
            with winreg.OpenKey(
                hive,
                "SOFTWARE\\Microsoft\\Windows\\CurrentVersion"
                f"\\App Paths\\{exe}",
                0,
                winreg.KEY_READ | view,
            ) as key:
                value = winreg.QueryValueEx(key, "")[0]
        except OSError:
            continue
        path = os.path.expandvars(str(value).strip('"'))
        if os.path.isfile(path):
            return path
    # Click-to-Run installs under root, MSI installs don't
    for root in ("%ProgramFiles%", "%ProgramFiles(x86)%"):
        for sub in ("root\\Office16", "Office16"):
            path = os.path.expandvars(
                f"{root}\\Microsoft Office\\{sub}\\{exe}"
            )
            if os.path.isfile(path):
                return path
    return None


def excel_chart_to_image(
    input_fpath: str,
    output_fpath: str,
    sheet: int = 1,
    chart_index: int = 0,
):
    """Export a chart from an Excel sheet to image."""
    import win32com.client
    from PIL import ImageGrab

    # Open the excel application using win32com
    excel = win32com.client.Dispatch("Excel.Application")
    # Disable alerts and visibility to the user
    excel.Visible = 0
    excel.DisplayAlerts = 0
    # Open workbook
    wb = excel.Workbooks.Open(os.path.abspath(input_fpath))
    # Extract sheet
    # TODO: Close workbook if something fails
    sheet = excel.Sheets(sheet)
    shape = sheet.Shapes[chart_index]
    shape.Copy()
    image = ImageGrab.grabclipboard()
    # Check if we need to change the mode of the image
    _, ext = os.path.splitext(output_fpath)
    if (
        ext in [".jpg", ".eps", ".tiff", ".gif", ".bmp"]
        and image.mode != "RGB"
    ):
        image = image.convert("RGB")
    # Save the image, overwriting if exists
    dirname = os.path.dirname(output_fpath)
    if dirname and not os.path.isdir(dirname):
        os.makedirs(dirname)
    image.save(os.path.abspath(output_fpath), quality=95, dpi=(300, 300))
    wb.Close(True)
    excel.Quit()
