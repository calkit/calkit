import json

import pytest

import calkit.google as gs


class FakeResponse:
    def __init__(self, status_code=200, body=None, content=b""):
        self.status_code = status_code
        self.ok = status_code < 400
        self._body = body if body is not None else {}
        self.content = content
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.headers = {}

    def _respond(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for (m, prefix), resp in self.routes.items():
            if m == method and url == prefix:
                return resp(kwargs) if callable(resp) else resp
        raise AssertionError(f"Unexpected {method} {url}")

    def get(self, url, **kwargs):
        return self._respond("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._respond("post", url, **kwargs)


def test_paths_and_ids(tmp_path):
    pid = "1AbCdEfGhIjKlMnOpQrStUvWxYz_-012"
    assert (
        gs.get_slides_presentation_id(
            f"https://docs.google.com/presentation/d/{pid}/edit#slide=id.p"
        )
        == pid
    )
    assert gs.get_slides_presentation_id(pid) == pid
    with pytest.raises(ValueError):
        gs.get_slides_presentation_id(
            "https://docs.google.com/document/d/x/edit"
        )
    assert gs.get_slides_presentation_url(pid).endswith(f"/d/{pid}/edit")
    assert gs.get_edit_time_path(pid) == f".calkit/google/{pid}.json"
    assert gs.get_figure_tag("figures/./a.png") == "calkit:figures/a.png"
    assert gs.get_figure_mime_type("a.JPG") == "image/jpeg"
    with pytest.raises(ValueError, match="PNG, JPEG, or GIF"):
        gs.get_figure_mime_type("a.pdf")
    assert gs.get_slides_export_mime_type("p.pdf") == "application/pdf"
    with pytest.raises(ValueError, match=".pdf or .pptx"):
        gs.get_slides_export_mime_type("p.png")
    # Writing the same edit time again changes nothing, so DVC sees no
    # change either
    path = str(tmp_path / "sub" / "edit.json")
    assert gs.write_edit_time(path, "2026-11-09T00:00:00Z")
    assert not gs.write_edit_time(path, "2026-11-09T00:00:00Z")
    assert gs.write_edit_time(path, "2026-11-09T01:00:00Z")
    with open(path) as f:
        assert json.load(f) == {"modified_time": "2026-11-09T01:00:00Z"}


def test_client():
    pid = "deck"
    file_url = f"{gs.DRIVE_API_URL}/{pid}"
    slides_url = f"{gs.SLIDES_API_URL}/{pid}"
    info = FakeResponse(
        body={
            "id": pid,
            "name": "Poster",
            "mimeType": gs.PRESENTATION_MIME_TYPE,
            "modifiedTime": "t1",
        }
    )
    tag = "calkit:figures/a.png"
    # A tagged image inside a group, and another tagged with a different
    # figure, which is left alone
    deck = FakeResponse(
        body={
            "slides": [
                {
                    "objectId": "s1",
                    "pageElements": [
                        {
                            "objectId": "g1",
                            "elementGroup": {
                                "children": [
                                    {
                                        "objectId": "img1",
                                        "image": {},
                                        "title": tag,
                                    }
                                ]
                            },
                        },
                        {
                            "objectId": "img2",
                            "image": {},
                            "title": "calkit:figures/b.png",
                        },
                    ],
                }
            ]
        }
    )
    batches = []

    def batch_update(kwargs):
        batches.append(kwargs["json"]["requests"])
        return FakeResponse()

    routes = {
        ("get", file_url): info,
        ("post", gs.DRIVE_API_URL): info,
        ("get", slides_url): deck,
        ("post", f"{slides_url}:batchUpdate"): batch_update,
    }
    client = gs.Client("token")
    client.http = FakeHttp(routes)  # type: ignore[assignment]
    expected = {
        "id": pid,
        "title": "Poster",
        "url": gs.get_slides_presentation_url(pid),
        "modified_time": "t1",
    }
    assert client.get_presentation_info(pid) == expected
    assert client.create_presentation("Poster") == expected
    # A tagged image is replaced where it is
    resp = client.put_figure(pid, "figures/a.png", "https://signed/a.png")
    assert resp == {"replaced": 1, "added": False, "modified_time": "t1"}
    assert batches[-1] == [
        {
            "replaceImage": {
                "imageObjectId": "img1",
                "url": "https://signed/a.png",
                "imageReplaceMethod": "CENTER_INSIDE",
            }
        }
    ]
    # A figure shown nowhere yet is added to the first slide, tagged
    resp = client.put_figure(pid, "figures/c.gif", "https://signed/c.gif")
    assert resp["added"] and resp["replaced"] == 0
    create, alt_text = batches[-1]
    assert create["createImage"]["elementProperties"] == {"pageObjectId": "s1"}
    assert alt_text["updatePageElementAltText"] == {
        "objectId": create["createImage"]["objectId"],
        "title": "calkit:figures/c.gif",
    }
    # What Slides says is wrong with an image is passed on
    routes[("post", f"{slides_url}:batchUpdate")] = FakeResponse(
        400, {"error": {"message": "Bad image"}}
    )
    with pytest.raises(gs.GoogleError, match="Bad image"):
        client.put_figure(pid, "figures/a.png", "https://signed/a.png")
    # Too big for the export API, so the file's export link is used
    export_url = f"{file_url}/export"
    routes[("get", export_url)] = FakeResponse(
        403, {"error": {"errors": [{"reason": "exportSizeLimitExceeded"}]}}
    )
    routes[("get", file_url)] = FakeResponse(
        body={"exportLinks": {"application/pdf": "https://export/pdf"}}
    )
    routes[("get", "https://export/pdf")] = FakeResponse(content=b"%PDF")
    assert client.export_presentation(pid, "application/pdf") == b"%PDF"
    # What Google refuses says what to do about it
    routes[("get", file_url)] = FakeResponse(
        403,
        {"error": {"errors": [{"reason": "insufficientPermissions"}]}},
    )
    with pytest.raises(gs.GoogleError, match="Connect Google Drive") as e:
        client.get_presentation_info(pid)
    assert e.value.status_code == 401
    routes[("get", file_url)] = FakeResponse(404, {"error": {}})
    with pytest.raises(gs.GoogleError, match="it created") as e:
        client.get_presentation_info(pid)
    assert e.value.status_code == 404
    routes[("get", file_url)] = FakeResponse(
        body={"id": pid, "mimeType": "application/pdf", "modifiedTime": "t"}
    )
    with pytest.raises(gs.GoogleError, match="isn't a Google Slides"):
        client.get_presentation_info(pid)


def test_is_same_export():
    import io
    import zipfile

    def pdf(date, doc_id, text):
        return (
            b"%PDF-1.4\n1 0 obj << /Producer (Skia/PDF) "
            b"/CreationDate (D:" + date + b") /ModDate <" + doc_id + b"> "
            b">> endobj\n<x:xmpmeta><xmp:CreateDate>" + date + b"</xmp:"
            b"CreateDate><xmpMM:DocumentID>uuid:" + doc_id + b"</xmpMM:"
            b"DocumentID></x:xmpmeta>\nBT (" + text + b") Tj ET\ntrailer "
            b"<< /ID [<" + doc_id + b"> <" + doc_id + b">] >>\n%%EOF"
        )

    def pptx(date, title, slide):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(
                "docProps/core.xml",
                f'<dc:title>{title}</dc:title><dcterms:modified xsi:type="W3"'
                f">{date}</dcterms:modified>",
            )
            z.writestr("ppt/slides/slide1.xml", slide)
        return buf.getvalue()

    old = pdf(b"20261109000000Z", b"AB12", b"Rates")
    assert gs.is_same_export(old, old, "p.pdf")
    # Only its dates and IDs differ
    assert gs.is_same_export(
        old, pdf(b"20261110120000Z", b"CD34", b"Rates"), "p.pdf"
    )
    assert not gs.is_same_export(
        old, pdf(b"20261110120000Z", b"CD34", b"Arrhenius"), "p.pdf"
    )
    old = pptx("2026-11-09T00:00:00Z", "Poster", "<p>Rates</p>")
    assert gs.is_same_export(
        old, pptx("2026-11-10T12:00:00Z", "Poster", "<p>Rates</p>"), "p.pptx"
    )
    assert not gs.is_same_export(
        old, pptx("2026-11-10T12:00:00Z", "Talk", "<p>Rates</p>"), "p.pptx"
    )
    assert not gs.is_same_export(
        old, pptx("2026-11-09T00:00:00Z", "Poster", "<p>Arr</p>"), "p.pptx"
    )
    # Anything that can't be read counts as changed
    assert not gs.is_same_export(b"not a zip", b"not a zip!", "p.pptx")
    assert not gs.is_same_export(b"a", b"b", "p.png")


def test_slide_figures(tmp_path):
    import io

    import pypdfium2 as pdfium

    pid = "1AbCdEfGhIjKlMnOpQrStUv"
    url = gs.get_slides_presentation_url(pid)
    assert gs.get_slide_id(f"{url}#slide=id.g2c3a1b9_0_12") == "g2c3a1b9_0_12"
    assert gs.get_slide_id(f"{url}?usp=sharing#slide=id.p") == "p"
    assert gs.get_slide_id(url) is None
    assert gs.get_slide_export_format("figures/a.PNG") == "png"
    with pytest.raises(ValueError, match=".pdf or .png"):
        gs.get_slide_export_format("figures/a.svg")
    # A presentation's figures go in the stage already exporting it
    ck_info = {
        "pipeline": {
            "stages": {
                "export-poster": {
                    "kind": "google-slides-export",
                    "presentation_url": url,
                    "outputs": ["poster.pdf"],
                },
                "plot": {"kind": "python-script", "outputs": ["fig.pdf"]},
            }
        }
    }
    assert gs.get_slides_stage_name(ck_info, pid, "Poster") == "export-poster"
    assert (
        gs.get_slides_stage_name({}, pid, "My Diagrams!")
        == "export-my-diagrams"
    )
    info = {"id": pid, "url": url}
    gs.add_slide_figure(ck_info, info, "s1", "figures/a.pdf", "export-poster")
    gs.add_slide_figure(ck_info, info, "s2", "figures/b.png", "new-stage")
    stages = ck_info["pipeline"]["stages"]
    assert stages["export-poster"]["slides"] == {"figures/a.pdf": "s1"}
    assert stages["new-stage"] == {
        "kind": "google-slides-export",
        "presentation_url": url,
        "slides": {"figures/b.png": "s2"},
    }
    for path, stage_name, match in [
        ("fig.pdf", "export-poster", "Stage 'plot' already makes"),
        ("figures/c.pdf", "plot", "doesn't export this presentation"),
        ("figures/c.svg", "export-poster", ".pdf or .png"),
    ]:
        with pytest.raises(ValueError, match=match):
            gs.add_slide_figure(ck_info, info, "s3", path, stage_name)
    # A slide is cut out of the deck's PDF, cropped to what's drawn on it,
    # with a margin for outlines, which is kept on the page
    doc = pdfium.PdfDocument.new()
    doc.new_page(720, 405)
    doc.new_page(720, 405)
    buf = io.BytesIO()
    doc.save(buf)
    deck_pdf = buf.getvalue()
    bounds = [200.0, 100.0, 560.0, 220.0]
    pdf = gs.get_slide_export(deck_pdf, 1, bounds, [720.0, 405.0], "a.pdf")
    page = pdfium.PdfDocument(pdf)[0]
    assert page.get_size() == pytest.approx((368, 128))
    png = gs.get_slide_export(
        deck_pdf, 0, bounds, [720.0, 405.0], "a.png", dpi=72, margin=0
    )
    from PIL import Image

    assert Image.open(io.BytesIO(png)).size == (360, 120)
    # The same slide exports to the same bytes, so nothing downstream reruns,
    # even a second later, since the time it's saved is left out
    import time

    time.sleep(1.1)
    assert (
        gs.get_slide_export(deck_pdf, 1, bounds, [720.0, 405.0], "a.pdf")
        == pdf
    )
    whole = gs.get_slide_export(
        deck_pdf, 0, [0, 0, 720, 405], [720.0, 405.0], "a.pdf"
    )
    assert pdfium.PdfDocument(whole)[0].get_size() == pytest.approx((720, 405))


def test_client_slides():
    pid = "deck"
    slides_url = f"{gs.SLIDES_API_URL}/{pid}"
    emu = gs.EMU_PER_POINT

    def size(w, h):
        return {
            "width": {"magnitude": w * emu, "unit": "EMU"},
            "height": {"magnitude": h * emu, "unit": "EMU"},
        }

    def notes(text, notes_id):
        content = [{"textRun": {"content": text}}] if text else []
        return {
            "notesPage": {
                "notesProperties": {"speakerNotesObjectId": notes_id},
                "pageElements": [
                    {
                        "objectId": notes_id,
                        "shape": {"text": {"textElements": content}},
                    }
                ],
            }
        }

    deck = {
        "pageSize": size(720, 405),
        "slides": [
            {
                # Only empty placeholders, so nothing is drawn
                "objectId": "title",
                "pageElements": [
                    {
                        "objectId": "t",
                        "size": size(600, 100),
                        "shape": {"placeholder": {"type": "TITLE"}},
                    }
                ],
                "slideProperties": notes("", "n1"),
            },
            {
                "objectId": "diagram",
                "pageElements": [
                    # A box in EMU, and a group moved by its own transform,
                    # whose child is scaled, in points
                    {
                        "objectId": "box",
                        "size": size(100, 50),
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": 200 * emu,
                            "translateY": 100 * emu,
                            "unit": "EMU",
                        },
                        "shape": {"shapeType": "RECTANGLE"},
                    },
                    {
                        "objectId": "group",
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": 400,
                            "translateY": 150,
                            "unit": "PT",
                        },
                        "elementGroup": {
                            "children": [
                                {
                                    "objectId": "child",
                                    "size": {
                                        "width": {
                                            "magnitude": 50,
                                            "unit": "PT",
                                        },
                                        "height": {
                                            "magnitude": 20,
                                            "unit": "PT",
                                        },
                                    },
                                    "transform": {
                                        "scaleX": 2,
                                        "scaleY": 2,
                                        "unit": "PT",
                                    },
                                }
                            ]
                        },
                    },
                    # Hanging off the slide's right edge
                    {
                        "objectId": "arrow",
                        "size": size(100, 10),
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": 680 * emu,
                            "translateY": 120 * emu,
                            "unit": "EMU",
                        },
                    },
                ],
                "slideProperties": notes("calkit:figures/a.pdf\n", "n2")
                | {"isSkipped": True},
            },
        ],
    }
    batches = []

    def batch_update(kwargs):
        batches.append(kwargs["json"]["requests"])
        return FakeResponse()

    client = gs.Client("token")
    client.http = FakeHttp(  # type: ignore[assignment]
        {
            ("get", slides_url): FakeResponse(body=deck),
            ("post", f"{slides_url}:batchUpdate"): batch_update,
        }
    )
    assert client.get_slides(pid) == {
        "page_size": [720.0, 405.0],
        "slides": [
            {
                "id": "title",
                "notes": "",
                "notes_id": "n1",
                "is_skipped": False,
                "bounds": None,
            },
            {
                "id": "diagram",
                "notes": "calkit:figures/a.pdf\n",
                "notes_id": "n2",
                "is_skipped": True,
                "bounds": [200.0, 100.0, 720.0, 190.0],
            },
        ],
    }
    # Only the tags not already in a slide's notes are added
    tags = {
        "figures/a.pdf": "diagram",
        "figures/a.png": "diagram",
        "figures/b.pdf": "title",
        "figures/c.pdf": "missing",
    }
    assert client.tag_slides(pid, tags) == 2
    assert batches[-1] == [
        {
            "insertText": {
                "objectId": "n2",
                "insertionIndex": 0,
                "text": "calkit:figures/a.png\n",
            }
        },
        {
            "insertText": {
                "objectId": "n1",
                "insertionIndex": 0,
                "text": "calkit:figures/b.pdf\n",
            }
        },
    ]
    n_batches = len(batches)
    assert client.tag_slides(pid, {"figures/a.pdf": "diagram"}) == 0
    assert len(batches) == n_batches
