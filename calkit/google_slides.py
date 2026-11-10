"""Exporting Google Slides presentations, and putting project figures in
them.

The hub makes these calls with each user's Google token, so the token
never leaves it; the CLI goes through the hub.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import uuid
from typing import Any

DRIVE_API_URL = "https://www.googleapis.com/drive/v3/files"
SLIDES_API_URL = "https://slides.googleapis.com/v1/presentations"
PRESENTATION_MIME_TYPE = "application/vnd.google-apps.presentation"
EXPORT_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument."
        "presentationml.presentation"
    ),
}
# What Slides can show
FIGURE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}
# What a slide can be exported to as a figure
SLIDE_EXPORT_FORMATS = {".pdf": "pdf", ".png": "png"}
# Put in an image's alt text title to say which project figure it shows,
# or in a slide's speaker notes to say which figure it's exported to
FIGURE_TAG_PREFIX = "calkit:"
EMU_PER_POINT = 12700
CONNECT_ADVICE = (
    "Connect Google Drive in your Calkit account settings, under "
    "Connected accounts."
)
NOT_FOUND_ADVICE = (
    "Calkit can only open presentations it created, or ones opened in "
    "Google Drive with Calkit."
)


class GoogleError(RuntimeError):
    """A request Google refused, with the HTTP status it gave."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def get_presentation_id(url: str) -> str:
    """The ID of a presentation, from its URL or the ID itself."""
    url = url.strip()
    match = re.search(r"/presentation/d/([A-Za-z0-9_-]+)", url)
    if match is not None:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", url):
        return url
    raise ValueError(f"Not a Google Slides URL: {url}")


def get_presentation_url(presentation_id: str) -> str:
    return f"https://docs.google.com/presentation/d/{presentation_id}/edit"


def get_edit_time_path(presentation_id: str) -> str:
    """Where the time a presentation was last edited is recorded, relative
    to the project, which a stage exporting it depends on.
    """
    return f".calkit/google-slides/{presentation_id}.json"


def write_edit_time(path: str, modified_time: str) -> bool:
    """Record when a presentation was last edited, returning whether that
    changed.
    """
    content = json.dumps({"modified_time": modified_time}, indent=2) + "\n"
    if os.path.isfile(path):
        with open(path) as f:
            if f.read() == content:
                return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return True


def get_default_stage_name(path: str) -> str:
    """The name of the stage exporting a presentation to ``path``, unless
    another is given, e.g., 'export-poster' for 'poster/poster.pdf'.
    """
    return "export-" + posixpath.splitext(posixpath.basename(path))[0]


def add_presentation(
    ck_info: dict,
    info: dict,
    path: str,
    kind: str | None = None,
    stage_name: str | None = None,
    figures: list[str] = [],
    pptx: bool = True,
) -> None:
    """Add a Google Slides presentation to a project's ``ck_info``, with the
    stage that exports it to ``path``, given what the hub says about it,
    e.g., its URL.

    Raises ``ValueError`` if it can't be added, e.g., if something is
    already at ``path``.
    """
    from calkit.models.pipeline import GoogleSlidesExportStage

    if kind is not None and kind not in ["slides", "poster"]:
        raise ValueError(
            "Presentation kind must be either 'slides' or 'poster'"
        )
    if not path.lower().endswith(".pdf"):
        raise ValueError(
            f"The exported presentation must be a PDF, not {path}"
        )
    if stage_name is None:
        stage_name = get_default_stage_name(path)
    outputs = [path]
    if pptx:
        outputs.append(path[:-4] + ".pptx")
    try:
        stage = GoogleSlidesExportStage(
            presentation_url=info["url"],
            figures=figures,
            outputs=outputs,  # type: ignore[arg-type]
        )
    except Exception as e:
        raise ValueError(f"Invalid stage specification: {e}")
    presentations = ck_info.get("presentations") or []
    if any(p.get("path") == path for p in presentations):
        raise ValueError(f"Presentation at path {path} already exists")
    stages = ck_info.setdefault("pipeline", {}).setdefault("stages", {})
    if stage_name in stages:
        raise ValueError(f"Stage '{stage_name}' already exists")
    presentation = {"path": path}
    if info.get("title"):
        presentation["title"] = info["title"]
    if kind is not None:
        presentation["kind"] = kind
    ck_info["presentations"] = presentations + [presentation]
    stages[stage_name] = stage.to_ck_dict()


def get_figure_tag(path: str) -> str:
    return FIGURE_TAG_PREFIX + posixpath.normpath(path.replace("\\", "/"))


def get_figure_mime_type(path: str) -> str:
    ext = posixpath.splitext(path)[1].lower()
    if ext not in FIGURE_MIME_TYPES:
        raise ValueError(
            f"Google Slides can't show {path}; figures in a presentation "
            "must be PNG, JPEG, or GIF"
        )
    return FIGURE_MIME_TYPES[ext]


def get_export_mime_type(path: str) -> str:
    ext = posixpath.splitext(path)[1].lower()
    if ext not in EXPORT_MIME_TYPES:
        raise ValueError(
            f"Google Slides can't export {path}; outputs must be .pdf or .pptx"
        )
    return EXPORT_MIME_TYPES[ext]


def get_slide_id(url: str) -> str | None:
    """The ID of the slide a presentation URL shows, e.g., 'g2c3a1b9_0_12'
    for one ending '#slide=id.g2c3a1b9_0_12'.
    """
    match = re.search(r"[#&]slide=id\.([A-Za-z0-9_-]+)", url)
    return match.group(1) if match is not None else None


def get_slide_export_format(path: str) -> str:
    """What a slide is exported to a figure as, from the figure's path."""
    ext = posixpath.splitext(path)[1].lower()
    if ext not in SLIDE_EXPORT_FORMATS:
        raise ValueError(
            f"A slide can't be exported to {path}; figures from slides must "
            "be .pdf or .png"
        )
    return SLIDE_EXPORT_FORMATS[ext]


def get_slides_stage_name(
    ck_info: dict, presentation_id: str, title: str | None
) -> str:
    """The stage that exports figures from a presentation's slides: the one
    already exporting it, if there is one, or else a new name from its
    title.
    """
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    for name, stage in stages.items():
        if (
            isinstance(stage, dict)
            and stage.get("kind") == "google-slides-export"
            and get_presentation_id(stage.get("presentation_url", ""))
            == presentation_id
        ):
            return str(name)
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return f"export-{slug or 'slides'}"


def add_slide_figure(
    ck_info: dict,
    info: dict,
    slide_id: str,
    path: str,
    stage_name: str,
) -> None:
    """Have ``stage_name`` export a slide to the figure at ``path``, adding
    the stage if it doesn't exist yet, given what the hub says about the
    presentation, e.g., its URL.

    Raises ``ValueError`` if it can't, e.g., if another stage already makes
    the figure.
    """
    from calkit.models.pipeline import GoogleSlidesExportStage

    get_slide_export_format(path)
    stages = ck_info.setdefault("pipeline", {}).setdefault("stages", {})
    stage = dict(stages.get(stage_name) or {})
    if stage and (
        stage.get("kind") != "google-slides-export"
        or get_presentation_id(stage.get("presentation_url", "")) != info["id"]
    ):
        raise ValueError(
            f"Stage '{stage_name}' doesn't export this presentation"
        )
    for name, other in stages.items():
        if name == stage_name or not isinstance(other, dict):
            continue
        outs = [
            o if isinstance(o, str) else o.get("path")
            for o in other.get("outputs") or []
        ] + list((other.get("slides") or {}).keys())
        if path in outs:
            raise ValueError(f"Stage '{name}' already makes {path}")
    if not stage:
        stage = {
            "kind": "google-slides-export",
            "presentation_url": info["url"],
        }
    stage["slides"] = dict(stage.get("slides") or {}) | {path: slide_id}
    try:
        GoogleSlidesExportStage.model_validate(stage)
    except Exception as e:
        raise ValueError(f"Invalid stage specification: {e}")
    stages[stage_name] = stage


def get_slide_export(
    deck_pdf: bytes,
    index: int,
    bounds: list[float],
    page_size: list[float],
    path: str,
    dpi: int = 300,
    margin: float = 4.0,
) -> bytes:
    """A figure made from one page of a presentation's PDF, cropped to what's
    drawn on it, as a PDF or PNG, depending on ``path``.

    ``bounds`` are what's drawn on the slide, in points from its top left,
    as ``get_slides`` gives them, and ``page_size`` is the slide's size.
    ``margin``, in points, keeps outlines, which straddle a shape's edge,
    from being cut in half.
    """
    import io

    import pypdfium2 as pdfium

    fmt = get_slide_export_format(path)
    src = pdfium.PdfDocument(deck_pdf)
    page = src[index]
    width, height = page.get_size()
    # The PDF's points should be the slide's, but are scaled to be sure
    sx, sy = width / page_size[0], height / page_size[1]
    left = max(bounds[0] * sx - margin, 0)
    right = min(bounds[2] * sx + margin, width)
    bottom = max(height - bounds[3] * sy - margin, 0)
    top = min(height - bounds[1] * sy + margin, height)
    buf = io.BytesIO()
    try:
        if fmt == "pdf":
            out = pdfium.PdfDocument.new()
            try:
                out.import_pages(src, [index])
                out_page = out[0]
                out_page.set_mediabox(left, bottom, right, top)
                out_page.set_cropbox(left, bottom, right, top)
                out.save(buf)
            finally:
                out.close()
            # pdfium gives each save a random ID, so the same slide would
            # export to a new file every time. It's in the trailer, after
            # every offset the file records, and only encrypted PDFs need
            # one.
            data = buf.getvalue()
            at = data.rfind(b"trailer")
            return data[:at] + re.sub(
                rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]",
                b"",
                data[at:],
            )
        else:
            bitmap = page.render(
                scale=dpi / 72,
                crop=(left, bottom, width - right, height - top),
            )
            bitmap.to_pil().save(buf, format="PNG")
    finally:
        src.close()
    return buf.getvalue()


def is_same_export(old: bytes, new: bytes, path: str) -> bool:
    """Whether two exports of a presentation differ only in what an export
    stamps on its own, e.g., the date, so keeping the old file avoids
    rerunning everything downstream of it.

    Anything that can't be read is taken as changed.
    """
    import io
    import zipfile

    def get_pdf_content(data: bytes) -> bytes:
        for pattern in [
            # Info dictionary dates, as literal or hex strings
            rb"/(CreationDate|ModDate)\s*(\([^)]*\)|<[0-9A-Fa-f]*>)",
            # The trailer ID, which is usually derived from the date
            rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]",
            # XMP metadata, when it isn't compressed
            rb"<(xmp:CreateDate|xmp:ModifyDate|xmp:MetadataDate|"
            rb"xmpMM:DocumentID|xmpMM:InstanceID)>[^<]*</\1>",
        ]:
            data = re.sub(pattern, b"", data)
        return data

    def get_pptx_content(data: bytes) -> dict[str, bytes] | None:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                content = {name: z.read(name) for name in z.namelist()}
        except (zipfile.BadZipFile, KeyError):
            return None
        # Its creation and modification times, but not, e.g., its title
        if "docProps/core.xml" in content:
            content["docProps/core.xml"] = re.sub(
                rb"<(dcterms:created|dcterms:modified)\b[^>]*>[^<]*</\1>",
                b"",
                content["docProps/core.xml"],
            )
        return content

    if old == new:
        return True
    ext = posixpath.splitext(path)[1].lower()
    if ext == ".pdf":
        return get_pdf_content(old) == get_pdf_content(new)
    if ext == ".pptx":
        old_content = get_pptx_content(old)
        return old_content is not None and old_content == get_pptx_content(new)
    return False


class Client:
    """Google Drive and Slides, with a user's OAuth token, which needs
    only the ``drive.file`` scope.
    """

    def __init__(self, token: str) -> None:
        import requests

        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {token}"

    def _check(self, resp: Any, action: str) -> None:
        if resp.ok:
            return
        try:
            error = resp.json().get("error", {})
            message = error.get("message", "")
            reasons = {e.get("reason") for e in error.get("errors", [])}
            reasons |= {
                d.get("reason")
                for d in error.get("details", [])
                if "reason" in d
            }
        except Exception:
            message, reasons = "", set()
        if resp.status_code == 401 or reasons & {
            "insufficientPermissions",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
        }:
            raise GoogleError(
                f"Google refused to let Calkit {action}. " + CONNECT_ADVICE,
                401,
            )
        if resp.status_code == 404:
            raise GoogleError(
                f"Google couldn't find the presentation to {action}. "
                + NOT_FOUND_ADVICE,
                404,
            )
        detail = f": {message}" if message else ""
        raise GoogleError(
            f"Failed to {action} (Google said HTTP {resp.status_code}"
            f"{detail})",
            resp.status_code,
        )

    def get_presentation_info(self, presentation_id: str) -> dict:
        """The presentation's ID, title, URL, and when it was last edited."""
        resp = self.http.get(
            f"{DRIVE_API_URL}/{presentation_id}",
            params={"fields": "id,name,mimeType,modifiedTime"},
            timeout=30,
        )
        self._check(resp, "open the presentation")
        file = resp.json()
        if file.get("mimeType") != PRESENTATION_MIME_TYPE:
            raise GoogleError(
                "That file isn't a Google Slides presentation", 422
            )
        return {
            "id": file["id"],
            "title": file.get("name"),
            "url": get_presentation_url(file["id"]),
            "modified_time": file["modifiedTime"],
        }

    def create_presentation(self, title: str) -> dict:
        """Create a blank presentation, returning what
        ``get_presentation_info`` does.
        """
        resp = self.http.post(
            DRIVE_API_URL,
            params={"fields": "id,name,mimeType,modifiedTime"},
            json={"name": title, "mimeType": PRESENTATION_MIME_TYPE},
            timeout=30,
        )
        self._check(resp, "create a presentation")
        file = resp.json()
        return {
            "id": file["id"],
            "title": file.get("name"),
            "url": get_presentation_url(file["id"]),
            "modified_time": file["modifiedTime"],
        }

    def export_presentation(
        self, presentation_id: str, mime_type: str
    ) -> bytes:
        """The presentation exported as a PDF or PowerPoint file."""
        resp = self.http.get(
            f"{DRIVE_API_URL}/{presentation_id}/export",
            params={"mimeType": mime_type},
            timeout=300,
        )
        # The export API stops at 10 MB, which a poster's images can pass,
        # but the file's own export link doesn't
        if resp.status_code == 403 and "exportSizeLimitExceeded" in resp.text:
            links = self.http.get(
                f"{DRIVE_API_URL}/{presentation_id}",
                params={"fields": "exportLinks"},
                timeout=30,
            )
            self._check(links, "export the presentation")
            link = links.json().get("exportLinks", {}).get(mime_type)
            if link is not None:
                resp = self.http.get(link, timeout=300)
        self._check(resp, "export the presentation")
        content: bytes = resp.content
        return content

    def put_figure(
        self, presentation_id: str, figure_path: str, image_url: str
    ) -> dict:
        """Replace every image tagged as showing a figure with its latest
        version, fetched by Slides from ``image_url``, keeping each one's
        place and size, or, if none is, add it to the first slide, tagged,
        for someone to move into place.

        Returns how many images were replaced, whether one was added, and
        when the presentation was then last edited.
        """
        tag = get_figure_tag(figure_path)

        def get_tagged_ids(elements: list[dict]) -> list[str]:
            ids = []
            for element in elements:
                if "elementGroup" in element:
                    ids += get_tagged_ids(
                        element["elementGroup"].get("children", [])
                    )
                elif "image" in element and element.get("title") == tag:
                    ids.append(element["objectId"])
            return ids

        resp = self.http.get(
            f"{SLIDES_API_URL}/{presentation_id}",
            params={"fields": "slides(objectId,pageElements)"},
            timeout=60,
        )
        self._check(resp, "read the presentation")
        slides = resp.json().get("slides", [])
        image_ids = []
        for slide in slides:
            image_ids += get_tagged_ids(slide.get("pageElements", []))
        if not image_ids and not slides:
            raise GoogleError(
                "The presentation has no slides to put the figure on", 422
            )
        batch: list[dict[str, Any]]
        if image_ids:
            batch = [
                {
                    "replaceImage": {
                        "imageObjectId": image_id,
                        "url": image_url,
                        "imageReplaceMethod": "CENTER_INSIDE",
                    }
                }
                for image_id in image_ids
            ]
        else:
            object_id = f"calkit_{uuid.uuid4().hex}"
            batch = [
                {
                    "createImage": {
                        "objectId": object_id,
                        "url": image_url,
                        "elementProperties": {
                            "pageObjectId": slides[0]["objectId"]
                        },
                    }
                },
                {
                    "updatePageElementAltText": {
                        "objectId": object_id,
                        "title": tag,
                    }
                },
            ]
        resp = self.http.post(
            f"{SLIDES_API_URL}/{presentation_id}:batchUpdate",
            json={"requests": batch},
            timeout=120,
        )
        self._check(resp, "put the figure in the presentation")
        info = self.get_presentation_info(presentation_id)
        return {
            "replaced": len(image_ids),
            "added": not image_ids,
            "modified_time": info["modified_time"],
        }

    def get_slides(self, presentation_id: str) -> dict:
        """The presentation's slides, in order, each with its ID, its speaker
        notes, whether it's skipped, and the bounds of what's drawn on it,
        in points from its top left, along with the size of a slide.
        """

        def get_points(dim: dict | None) -> float:
            if not dim:
                return 0.0
            magnitude = float(dim.get("magnitude", 0))
            return (
                magnitude / EMU_PER_POINT
                if dim.get("unit") == "EMU"
                else magnitude
            )

        def get_matrix(transform: dict | None) -> list[float]:
            # Omitted fields are zero, but an omitted transform is identity
            if transform is None:
                return [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            unit = EMU_PER_POINT if transform.get("unit") == "EMU" else 1
            return [
                float(transform.get("scaleX", 0)),
                float(transform.get("shearY", 0)),
                float(transform.get("shearX", 0)),
                float(transform.get("scaleY", 0)),
                float(transform.get("translateX", 0)) / unit,
                float(transform.get("translateY", 0)) / unit,
            ]

        def compose(outer: list[float], inner: list[float]) -> list[float]:
            a, b, c, d, e, f = outer
            a2, b2, c2, d2, e2, f2 = inner
            return [
                a * a2 + c * b2,
                b * a2 + d * b2,
                a * c2 + c * d2,
                b * c2 + d * d2,
                a * e2 + c * f2 + e,
                b * e2 + d * f2 + f,
            ]

        def get_text(shape: dict) -> str:
            return "".join(
                t.get("textRun", {}).get("content", "")
                for t in (shape.get("text") or {}).get("textElements", [])
            )

        def get_corners(
            elements: list[dict], parent: list[float]
        ) -> list[tuple[float, float]]:
            corners = []
            for element in elements:
                matrix = compose(parent, get_matrix(element.get("transform")))
                if "elementGroup" in element:
                    corners += get_corners(
                        element["elementGroup"].get("children", []), matrix
                    )
                    continue
                shape = element.get("shape") or {}
                # An empty placeholder, e.g., "Click to add title", isn't
                # drawn
                if "placeholder" in shape and not get_text(shape).strip():
                    continue
                size = element.get("size") or {}
                w, h = (
                    get_points(size.get("width")),
                    get_points(size.get("height")),
                )
                a, b, c, d, e, f = matrix
                for x, y in [(0, 0), (w, 0), (0, h), (w, h)]:
                    corners.append((a * x + c * y + e, b * x + d * y + f))
            return corners

        resp = self.http.get(
            f"{SLIDES_API_URL}/{presentation_id}",
            params={
                "fields": (
                    "pageSize,slides(objectId,pageElements,slideProperties("
                    "isSkipped,notesPage(notesProperties,pageElements)))"
                )
            },
            timeout=60,
        )
        self._check(resp, "read the presentation")
        deck = resp.json()
        page_size = [
            get_points(deck.get("pageSize", {}).get("width")),
            get_points(deck.get("pageSize", {}).get("height")),
        ]
        slides = []
        for slide in deck.get("slides", []):
            props = slide.get("slideProperties") or {}
            notes_page = props.get("notesPage") or {}
            notes_id = (notes_page.get("notesProperties") or {}).get(
                "speakerNotesObjectId"
            )
            notes = "".join(
                get_text(e.get("shape") or {})
                for e in notes_page.get("pageElements", [])
                if e.get("objectId") == notes_id
            )
            corners = get_corners(
                slide.get("pageElements", []), get_matrix(None)
            )
            bounds = None
            if corners:
                xs = [x for x, _ in corners]
                ys = [y for _, y in corners]
                # What hangs off the slide isn't exported
                bounds = [
                    max(min(xs), 0.0),
                    max(min(ys), 0.0),
                    min(max(xs), page_size[0]),
                    min(max(ys), page_size[1]),
                ]
                if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                    bounds = None
            slides.append(
                {
                    "id": slide["objectId"],
                    "notes": notes,
                    "notes_id": notes_id,
                    "is_skipped": bool(props.get("isSkipped")),
                    "bounds": bounds,
                }
            )
        return {"page_size": page_size, "slides": slides}

    def tag_slides(self, presentation_id: str, tags: dict[str, str]) -> int:
        """Say in each slide's speaker notes which figures it's exported to,
        given slide IDs by figure path, unless they already do, returning
        how many tags were added.
        """
        slides = {
            s["id"]: s for s in self.get_slides(presentation_id)["slides"]
        }
        batch = []
        for path, slide_id in tags.items():
            slide = slides.get(slide_id)
            tag = get_figure_tag(path)
            if slide is None or slide["notes_id"] is None:
                continue
            if tag in slide["notes"].splitlines():
                continue
            batch.append(
                {
                    "insertText": {
                        "objectId": slide["notes_id"],
                        "insertionIndex": 0,
                        "text": tag + "\n",
                    }
                }
            )
        if batch:
            resp = self.http.post(
                f"{SLIDES_API_URL}/{presentation_id}:batchUpdate",
                json={"requests": batch},
                timeout=120,
            )
            self._check(resp, "tag the slides")
        return len(batch)
