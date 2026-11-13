"""Functionality for working with Microsoft Office."""

import os
import sys

from calkit.windows import is_wsl


def excel_chart_to_image(
    input_fpath: str,
    output_fpath: str,
    sheet: int = 1,
    chart_index: int = 0,
):
    """Export a chart from an Excel sheet to image."""
    if sys.platform == "win32":
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
    elif is_wsl():
        raise NotImplementedError(
            "Exporting Excel charts to images is not yet implemented for WSL"
        )
        from calkit.windows import wsl_run_powershell_cmd

        PS_SCRIPT = r"""
todo
"""
        wsl_run_powershell_cmd(PS_SCRIPT)
    else:
        raise NotImplementedError(
            "Exporting Excel charts to images is only supported on Windows"
        )
