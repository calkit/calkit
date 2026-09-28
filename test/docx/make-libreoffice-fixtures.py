"""Make the LibreOffice review fixtures.

Exports the fixture paper as the round trip test does, then has LibreOffice
edit a sentence, comment, and change the equation's C_T to C_P with changes
tracked, saving ``libreoffice-returned.docx``, and accept them all, saving
``libreoffice-accepted.docx``. LibreOffice doesn't track changes inside
equations, so the equation edit is already in the returned file.

Run from the repo root with ``uv run python test/docx/make-libreoffice-fixtures.py``.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import calkit.cli.latex
import calkit.docx

HERE = Path(__file__).resolve().parent
SOFFICE = shutil.which("soffice") or (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice"
)
MACRO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
Sub Review(src As String, returned As String, accepted As String)
  cp = createUnoService("com.sun.star.configuration.ConfigurationProvider")
  Dim node(0) As New com.sun.star.beans.PropertyValue
  node(0).Name = "nodepath"
  node(0).Value = "/org.openoffice.UserProfile/Data"
  user = cp.createInstanceWithArguments("com.sun.star.configuration.ConfigurationUpdateAccess", node())
  user.setPropertyValue("givenname", "Libre")
  user.setPropertyValue("sn", "Reviewer")
  user.commitChanges()
  Dim args(0) As New com.sun.star.beans.PropertyValue
  args(0).Name = "Hidden"
  args(0).Value = True
  doc = StarDesktop.loadComponentFromURL(ConvertToURL(src), "_blank", 0, args())
  doc.RecordChanges = True
  sd = doc.createSearchDescriptor()
  sd.SearchString = "Wakes matter"
  found = doc.findFirst(sd)
  found.setString("Wakes really matter")
  sd.SearchString = "reasonably well"
  found = doc.findFirst(sd)
  ann = doc.createInstance("com.sun.star.text.textfield.Annotation")
  ann.Author = "Libre Reviewer"
  ann.Content = "Quantify this."
  found.getText().insertTextContent(found, ann, True)
  objs = doc.getEmbeddedObjects()
  For i = 0 To objs.getCount() - 1
    model = objs.getByIndex(i).getEmbeddedObject()
    If InStr(model.Formula, "{C} rsub {T}") > 0 Then
      model.Formula = Replace(model.Formula, "{C} rsub {T}", "{C} rsub {P}")
    End If
  Next i
  Dim sargs(0) As New com.sun.star.beans.PropertyValue
  sargs(0).Name = "FilterName"
  sargs(0).Value = "MS Word 2007 XML"
  doc.storeToURL(ConvertToURL(returned), sargs())
  disp = createUnoService("com.sun.star.frame.DispatchHelper")
  disp.executeDispatch(doc.getCurrentController().getFrame(), ".uno:AcceptAllTrackedChanges", "", 0, Array())
  doc.storeToURL(ConvertToURL(accepted), sargs())
  doc.close(True)
  StarDesktop.terminate()
End Sub
</script:module>
"""

if calkit.docx.find_pandoc() is None:
    sys.exit("Pandoc is needed to export the equations")
with tempfile.TemporaryDirectory() as tmp:
    project, profile = Path(tmp, "project"), Path(tmp, "profile")
    os.makedirs(project / "paper")
    for name in ["main.tex", "methods.tex"]:
        shutil.copy(HERE / name, project / "paper" / name)
    (project / "calkit.yaml").write_text("")
    (project / "paper" / "main.pdf").write_bytes(b"")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    os.chdir(project)
    calkit.docx.pdf_to_docx = lambda _, out: shutil.copy(
        HERE / "word-import.docx", out
    )
    calkit.cli.latex.to_docx("paper/main.pdf")
    # A first start sets up the profile the macro goes into
    lo = [SOFFICE, f"-env:UserInstallation={profile.as_uri()}", "--headless"]
    subprocess.run([*lo, "--terminate_after_init"], check=True, timeout=120)
    (profile / "user" / "basic" / "Standard" / "Module1.xba").write_text(
        MACRO, encoding="utf-8"
    )
    paths = [
        project / "paper" / "main-for-review.docx",
        HERE / "libreoffice-returned.docx",
        HERE / "libreoffice-accepted.docx",
    ]
    args = ",".join(f'"{p}"' for p in paths)
    subprocess.run(
        [*lo, "--norestore", f"macro:///Standard.Module1.Review({args})"],
        check=True,
        timeout=120,
    )
