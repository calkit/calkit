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


def is_office_app_installed(app: str) -> bool:
    """Whether an Office app, e.g., Word, is installed, which only it can
    tell on Windows, through the path it registers."""
    exe, bundle = OFFICE_APPS[app]
    if sys.platform == "darwin":
        return any(
            os.path.isdir(os.path.expanduser(f"{d}/{bundle}.app"))
            for d in ("/Applications", "~/Applications")
        )
    if sys.platform == "win32":
        import winreg

        # Machine-wide, else for this user, as Office installs either way
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                winreg.CloseKey(
                    winreg.OpenKey(
                        hive,
                        "SOFTWARE\\Microsoft\\Windows\\CurrentVersion"
                        f"\\App Paths\\{exe}",
                    )
                )
            except OSError:
                continue
            return True
        return False
    return False


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
