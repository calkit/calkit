import io
import os
import posixpath
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pypdfium2 as pdfium
import pytest
from PIL import Image

from calkit.pptx import CT, A, P, Placement, R, update_figures

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "..", "test", "figures.pptx"
)


def test_update_figures(tmp_path: Path) -> None:
    def pictures(path: Path, slide: int) -> dict[str, dict]:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read(f"ppt/slides/slide{slide}.xml"))
            rels = {
                r.get("Id"): posixpath.normpath(
                    posixpath.join("ppt/slides", r.get("Target", ""))
                )
                for r in ET.fromstring(
                    z.read(f"ppt/slides/_rels/slide{slide}.xml.rels")
                )
            }
            out = {}
            for pic in root.iter(f"{{{P}}}pic"):
                name = pic.find(f"{{{P}}}nvPicPr/{{{P}}}cNvPr")
                blip_fill = pic.find(f"{{{P}}}blipFill")
                assert name is not None and blip_fill is not None
                blip = blip_fill.find(f"{{{A}}}blip")
                size = pic.find(f"{{{P}}}spPr/{{{A}}}xfrm/{{{A}}}ext")
                assert blip is not None and size is not None
                media = rels[blip.get(f"{{{R}}}embed")]
                out[name.get("name", "")] = {
                    "media": media,
                    "data": z.read(media),
                    "cx": int(size.get("cx", 0)),
                    "cy": int(size.get("cy", 0)),
                    "cropped": blip_fill.find(f"{{{A}}}srcRect") is not None,
                }
            return out

    def media(path: Path) -> list[str]:
        with zipfile.ZipFile(path) as z:
            return sorted(n for n in z.namelist() if "/media/" in n)

    deck = tmp_path / "deck.pptx"
    shutil.copy(FIXTURE, deck)
    original = deck.read_bytes()
    # A wide plot, a tall PDF, and a JPEG logo
    Image.new("RGB", (600, 200), "orange").save(tmp_path / "wide.png")
    Image.new("RGB", (200, 400), "purple").save(tmp_path / "tall.pdf")
    Image.new("RGB", (50, 50), "black").save(tmp_path / "logo.jpg")
    wide = (tmp_path / "wide.png").read_bytes()
    before = {n: pictures(deck, n) for n in (1, 2, 3)}
    # What can't be placed says why, and writes nothing
    for placements, error in [
        ([Placement(slide=9, path="wide.png")], "has 3 slides"),
        ([Placement(slide=2, path="wide.png")], "has 2 pictures"),
        (
            [Placement(slide=2, path="wide.png", picture="Nope")],
            "no picture named 'Nope'",
        ),
        ([Placement(slide=1, path="gone.png")], "doesn't exist"),
        (
            [
                Placement(slide=1, path=str(tmp_path / "wide.png")),
                Placement(slide=9, path=str(tmp_path / "wide.png")),
            ],
            "has 3 slides",
        ),
    ]:
        with pytest.raises(ValueError, match=error):
            update_figures(str(deck), placements)
    (tmp_path / "plot.svg").write_text("<svg/>")
    with pytest.raises(ValueError, match="PNG, JPEG, or PDF"):
        update_figures(
            str(deck), [Placement(slide=1, path=str(tmp_path / "plot.svg"))]
        )
    with pytest.raises(ValueError, match="isn't a PowerPoint file"):
        update_figures(str(tmp_path / "wide.png"), [])
    assert deck.read_bytes() == original
    # The only picture on slide 1, into a new file: as wide as it was, its
    # height from the plot's shape, and its crop gone, while slide 2 still
    # shows the image the two shared
    out = tmp_path / "out" / "deck.pptx"
    update_figures(
        str(deck),
        [Placement(slide=1, path=str(tmp_path / "wide.png"))],
        output=str(out),
    )
    assert deck.read_bytes() == original
    plot = pictures(out, 1)["Plot"]
    assert plot["data"] == wide
    assert plot["cx"] == before[1]["Plot"]["cx"]
    assert plot["cy"] == round(plot["cx"] / 3)
    assert before[1]["Plot"]["cropped"] and not plot["cropped"]
    assert pictures(out, 2) == before[2]
    assert len(media(out)) == 4
    # Slide 2's, in place: the same plot is stored once, the image nothing
    # shows anymore is gone, and the logo, as a JPEG, gets its type listed
    update_figures(
        str(out),
        [
            Placement(
                slide=2, path=str(tmp_path / "wide.png"), picture="Plot"
            ),
            Placement(
                slide=2, path=str(tmp_path / "logo.jpg"), picture="Logo"
            ),
        ],
    )
    after = pictures(out, 2)
    assert after["Plot"]["media"] == plot["media"]
    assert after["Plot"]["cy"] == round(after["Plot"]["cx"] / 3)
    assert after["Logo"]["cy"] == after["Logo"]["cx"]
    assert before[1]["Plot"]["media"] not in media(out)
    assert before[2]["Logo"]["media"] not in media(out)
    with zipfile.ZipFile(out) as z:
        types = ET.fromstring(z.read("[Content_Types].xml"))
    assert "jpg" in {
        d.get("Extension") for d in types.iter(f"{{{CT}}}Default")
    }
    # In a group stretched to twice its width, a PDF figure keeps its own
    # shape as shown
    update_figures(
        str(out),
        [Placement(slide=3, path=str(tmp_path / "tall.pdf"))],
        dpi=150,
    )
    grouped = pictures(out, 3)["Grouped"]
    assert grouped["cx"] == before[3]["Grouped"]["cx"]
    assert grouped["cy"] == round(grouped["cx"] * 2 * 2)
    with Image.open(io.BytesIO(grouped["data"])) as image:
        assert image.size == (
            pytest.approx(417, abs=1),
            pytest.approx(833, abs=1),
        )
    # The same updates make the same file
    again = tmp_path / "again.pptx"
    update_figures(
        str(deck),
        [Placement(slide=1, path=str(tmp_path / "wide.png"))],
        output=str(again),
    )
    update_figures(
        str(again),
        [
            Placement(
                slide=2, path=str(tmp_path / "wide.png"), picture="Plot"
            ),
            Placement(
                slide=2, path=str(tmp_path / "logo.jpg"), picture="Logo"
            ),
        ],
    )
    update_figures(
        str(again),
        [Placement(slide=3, path=str(tmp_path / "tall.pdf"))],
        dpi=150,
    )
    assert again.read_bytes() == out.read_bytes()
    # LibreOffice opens it, when it's here to
    soffice = shutil.which("soffice") or next(
        (
            p
            for p in [
                "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                r"C:\Program Files\LibreOffice\program\soffice.exe",
            ]
            if os.path.isfile(p)
        ),
        None,
    )
    if soffice is not None:
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={(tmp_path / 'profile').as_uri()}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_path / "pdf"),
                str(out),
            ],
            capture_output=True,
            check=True,
        )
        pdf = pdfium.PdfDocument(tmp_path / "pdf" / "deck.pdf")
        try:
            assert len(pdf) == 3
        finally:
            pdf.close()
