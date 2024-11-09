"""Functionality for working with Microsoft Office."""

import os

from PIL import ImageGrab


def excel_chart_to_png(
    input_fpath: str,
    output_fpath: str,
    sheet: int = 1,
    chart_index: int = 0,
):
    """Export a chart from an Excel sheet to PNG."""
    import win32com.client

    # Open the excel application using win32com
    excel = win32com.client.Dispatch("Excel.Application")
    # Disable alerts and visibility to the user
    excel.Visible = 0
    excel.DisplayAlerts = 0
    # Open workbook
    wb = excel.Workbooks.Open(os.path.abspath(input_fpath))
    factor = 1.0
    # Extract sheet
    # TODO: Close workbook if something fails
    sheet = excel.Sheets(sheet)
    shape = sheet.Shapes[chart_index]
    shape.Copy()
    image = ImageGrab.grabclipboard()
    length_x, width_y = image.size
    size = int(factor * length_x), int(factor * width_y)
    image_resize = image.resize(size)
    # Save the image into the existing png file, overwriting if exists
    dirname = os.path.dirname(output_fpath)
    if dirname and not os.path.isdir(dirname):
        os.makedirs(dirname)
    image_resize.save(
        os.path.abspath(output_fpath), "png", quality=95, dpi=(300, 300)
    )
    wb.Close(True)
    excel.Quit()
