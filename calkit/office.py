"""Functionality for working with Microsoft Office."""

from PIL import ImageGrab


def excel_charts_to_png(
    inputExcelFilePath: str, outputPNGImagePath: str, sheet: int = 1
):
    import win32com

    # Open the excel application using win32com
    o = win32com.client.Dispatch("Excel.Application")
    # Disable alerts and visibility to the user
    o.Visible = 0
    o.DisplayAlerts = 0
    # Open workbook
    wb = o.Workbooks.Open(inputExcelFilePath)
    factor = 1.0
    # Extract sheet
    sheet = o.Sheets(sheet)
    for n, shape in enumerate(sheet.Shapes):
        # Save shape to clipboard, then save what is in the clipboard to the file
        shape.Copy()
        image = ImageGrab.grabclipboard()
        length_x, width_y = image.size
        size = int(factor * length_x), int(factor * width_y)
        image_resize = image.resize(size)
        # Saves the image into the existing png file (overwriting)
        outputPNGImage = outputPNGImagePath + str(n) + ".png"
        image_resize.save(outputPNGImage, "png", quality=95, dpi=(300, 300))
    wb.Close(True)
    o.Quit()
