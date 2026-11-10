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
SLIDES_EXPORT_MIME_TYPES = {
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
# Put in an image's alt text title to say which project figure it shows
FIGURE_TAG_PREFIX = "calkit:"
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


def get_slides_presentation_id(url: str) -> str:
    """The ID of a presentation, from its URL or the ID itself."""
    url = url.strip()
    match = re.search(r"/presentation/d/([A-Za-z0-9_-]+)", url)
    if match is not None:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", url):
        return url
    raise ValueError(f"Not a Google Slides URL: {url}")


def get_slides_presentation_url(presentation_id: str) -> str:
    return f"https://docs.google.com/presentation/d/{presentation_id}/edit"


def get_edit_time_path(presentation_id: str) -> str:
    """Where the time a presentation was last edited is recorded, relative
    to the project, which a stage exporting it depends on.
    """
    return f".calkit/google/{presentation_id}.json"


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


def get_default_slides_stage_name(path: str) -> str:
    """The name of the stage exporting a presentation to ``path``, unless
    another is given, e.g., 'export-poster' for 'poster/poster.pdf'.
    """
    return "export-" + posixpath.splitext(posixpath.basename(path))[0]


def add_slides_presentation(
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
    from calkit.pipeline import get_stage_for_output

    if kind is not None and kind not in ["slides", "poster"]:
        raise ValueError(
            "Presentation kind must be either 'slides' or 'poster'"
        )
    if not path.lower().endswith(".pdf"):
        raise ValueError(
            f"The exported presentation must be a PDF, not {path}"
        )
    if stage_name is None:
        stage_name = get_default_slides_stage_name(path)
    outputs = [path]
    if pptx:
        outputs.append(path[:-4] + ".pptx")
    # The figures are the stage's inputs, and must be images Slides can show
    for figure in figures:
        get_figure_mime_type(figure)
    try:
        stage = GoogleSlidesExportStage(
            presentation_url=info["url"],
            inputs=figures,  # type: ignore[arg-type]
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
    for out in outputs:
        other = get_stage_for_output(out, ck_info)
        if other is not None:
            raise ValueError(f"{out} is already an output of stage '{other}'")
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


def get_slides_export_mime_type(path: str) -> str:
    ext = posixpath.splitext(path)[1].lower()
    if ext not in SLIDES_EXPORT_MIME_TYPES:
        raise ValueError(
            f"Google Slides can't export {path}; outputs must be .pdf or .pptx"
        )
    return SLIDES_EXPORT_MIME_TYPES[ext]


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

    ``account`` is the email of the Google account the token is for, when
    known, since one person can connect more than one.
    """

    def __init__(self, token: str, account: str | None = None) -> None:
        import requests

        self.account = account
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
            "url": get_slides_presentation_url(file["id"]),
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
            "url": get_slides_presentation_url(file["id"]),
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

    def share_file(self, file_id: str, email: str | None = None) -> None:
        """Let the Google account with ``email`` edit a file, without
        emailing them, or, without an email, anyone with its link view it.
        """
        permission: dict[str, Any]
        if email is not None:
            permission = {
                "type": "user",
                "role": "writer",
                "emailAddress": email,
            }
            params = {"sendNotificationEmail": "false"}
        else:
            permission = {
                "type": "anyone",
                "role": "reader",
                "allowFileDiscovery": False,
            }
            params = {}
        resp = self.http.post(
            f"{DRIVE_API_URL}/{file_id}/permissions",
            params=params,
            json=permission,
            timeout=30,
        )
        self._check(resp, "share the file")

    def unshare_file(self, file_id: str) -> None:
        """Stop anyone with a file's link being able to view it, if they
        could.
        """
        resp = self.http.delete(
            f"{DRIVE_API_URL}/{file_id}/permissions/anyoneWithLink",
            timeout=30,
        )
        if resp.status_code == 404:
            return
        self._check(resp, "stop sharing the file")
