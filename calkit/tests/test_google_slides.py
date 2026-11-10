import json

import pytest

import calkit.google_slides as gs


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
        gs.get_presentation_id(
            f"https://docs.google.com/presentation/d/{pid}/edit#slide=id.p"
        )
        == pid
    )
    assert gs.get_presentation_id(pid) == pid
    with pytest.raises(ValueError):
        gs.get_presentation_id("https://docs.google.com/document/d/x/edit")
    assert gs.get_presentation_url(pid).endswith(f"/d/{pid}/edit")
    assert gs.get_edit_time_path(pid) == f".calkit/google-slides/{pid}.json"
    assert gs.get_figure_tag("figures/./a.png") == "calkit:figures/a.png"
    assert gs.get_figure_mime_type("a.JPG") == "image/jpeg"
    with pytest.raises(ValueError, match="PNG, JPEG, or GIF"):
        gs.get_figure_mime_type("a.pdf")
    assert gs.get_export_mime_type("p.pdf") == "application/pdf"
    with pytest.raises(ValueError, match=".pdf or .pptx"):
        gs.get_export_mime_type("p.png")
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
        "url": gs.get_presentation_url(pid),
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
