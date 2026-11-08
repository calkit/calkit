"""Editing PowerPoint files, e.g., to put a pipeline's figures in a deck."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import posixpath
import tempfile
import zipfile
from xml.etree import ElementTree as ET

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
IMAGE_REL = R + "/image"
# Where PowerPoint keeps an SVG, beside the PNG older versions show
SVG_BLIP_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


@dataclasses.dataclass
class Placement:
    """A figure to put in place of a picture on a slide."""

    slide: int
    path: str
    # Its name in PowerPoint's selection pane, which can be left out when
    # it's the slide's only picture
    picture: str | None = None


def update_figures(
    source: str,
    placements: list[Placement],
    output: str | None = None,
    dpi: int = 300,
) -> None:
    """Put each figure in place of its picture, keeping the picture's
    position and width, so its height follows the figure's shape.

    Writes ``output``, or ``source`` itself if there's none, raising
    ``ValueError`` before writing anything if a figure has nowhere to go.
    A PDF figure becomes a PNG at ``dpi``.
    """
    from PIL import Image

    from calkit.docx import _dump, _parse

    def tag(ns: str, name: str) -> str:
        return f"{{{ns}}}{name}"

    def rels_part(part: str) -> str:
        folder, name = posixpath.split(part)
        return posixpath.join(folder, "_rels", name + ".rels")

    def rels_source(rels: str) -> str:
        folder, name = posixpath.split(rels)
        return posixpath.join(posixpath.dirname(folder), name[: -len(".rels")])

    def target_part(part: str, target: str) -> str:
        if target.startswith("/"):
            return target.lstrip("/")
        return posixpath.normpath(
            posixpath.join(posixpath.dirname(part), target)
        )

    def figure_image(path: str) -> tuple[bytes, str, tuple[int, int]]:
        """The figure's bytes as a picture, their extension, and its size."""
        ext = os.path.splitext(path)[1].lower()
        if not os.path.isfile(path):
            raise ValueError(f"'{path}' doesn't exist")
        if ext == ".pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(path)
            try:
                image = pdf[0].render(scale=dpi / 72).to_pil()
            finally:
                pdf.close()
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue(), ".png", image.size
        if ext not in IMAGE_TYPES:
            raise ValueError(
                f"A figure in a slide can be a PNG, JPEG, or PDF, not '{path}'"
            )
        with open(path, "rb") as f:
            data = f.read()
        with Image.open(io.BytesIO(data)) as image:
            return data, ext, image.size

    if os.path.splitext(source)[1].lower() not in (".pptx", ".pptm"):
        raise ValueError(f"'{source}' isn't a PowerPoint file")
    with zipfile.ZipFile(source) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    # The slides in order, as the presentation lists them
    main = next(
        target_part("", r.get("Target", ""))
        for r in ET.fromstring(parts["_rels/.rels"])
        if r.get("Type", "").endswith("/officeDocument")
    )
    main_rels = {
        r.get("Id"): target_part(main, r.get("Target", ""))
        for r in ET.fromstring(parts[rels_part(main)])
    }
    slides = [
        main_rels[s.get(tag(R, "id"), "")]
        for s in ET.fromstring(parts[main]).iter(tag(P, "sldId"))
    ]
    content_types = _parse(parts["[Content_Types].xml"])
    edited: dict[str, ET.Element] = {}
    unlinked: set[str] = set()
    for placement in placements:
        if not 1 <= placement.slide <= len(slides):
            raise ValueError(
                f"'{source}' has {len(slides)} slides, "
                f"so there's no slide {placement.slide}"
            )
        slide = slides[placement.slide - 1]
        rels = rels_part(slide)
        for part in (slide, rels):
            if part not in edited:
                edited[part] = _parse(parts[part])
        root, rels_root = edited[slide], edited[rels]
        # Which picture it replaces
        pictures = list(root.iter(tag(P, "pic")))
        names = [
            pic.find(f"{tag(P, 'nvPicPr')}/{tag(P, 'cNvPr')}")
            for pic in pictures
        ]
        matches = [
            pic
            for pic, name in zip(pictures, names)
            if placement.picture is None
            or (name is not None and name.get("name") == placement.picture)
        ]
        if placement.picture is None and len(pictures) != 1:
            raise ValueError(
                f"Slide {placement.slide} has {len(pictures)} pictures, "
                "so say which by its name"
            )
        if len(matches) != 1:
            raise ValueError(
                f"Slide {placement.slide} has {len(matches) or 'no'} "
                f"picture{'s' * (len(matches) > 1)} named "
                f"'{placement.picture}'"
            )
        pic = matches[0]
        blip_fill = pic.find(tag(P, "blipFill"))
        blip = None if blip_fill is None else blip_fill.find(tag(A, "blip"))
        if blip_fill is None or blip is None:
            raise ValueError(
                f"Picture '{placement.picture}' on slide {placement.slide} "
                "has no image to replace"
            )
        # The figure, named for its content so the same one is stored once
        data, ext, (width, height) = figure_image(placement.path)
        media = posixpath.join(
            posixpath.dirname(posixpath.dirname(slide)),
            "media",
            f"calkit-{hashlib.sha256(data).hexdigest()[:16]}{ext}",
        )
        parts[media] = data
        if not any(
            d.get("Extension", "").lower() == ext[1:]
            for d in content_types.iter(tag(CT, "Default"))
        ):
            default = ET.Element(
                tag(CT, "Default"),
                {"Extension": ext[1:], "ContentType": IMAGE_TYPES[ext]},
            )
            content_types.insert(0, default)
        rel_id = next(
            (
                r.get("Id")
                for r in rels_root
                if r.get("Type") == IMAGE_REL
                and target_part(slide, r.get("Target", "")) == media
            ),
            None,
        )
        if rel_id is None:
            ids = {r.get("Id") for r in rels_root}
            rel_id = next(
                f"rId{n}"
                for n in range(1, len(ids) + 2)
                if f"rId{n}" not in ids
            )
            ET.SubElement(
                rels_root,
                tag(PKG_REL, "Relationship"),
                {
                    "Id": rel_id,
                    "Type": IMAGE_REL,
                    "Target": posixpath.relpath(
                        media, posixpath.dirname(slide)
                    ),
                },
            )
        blip.set(tag(R, "embed"), rel_id)
        # Neither an SVG of the old figure nor a crop made for it applies
        ext_list = blip.find(tag(A, "extLst"))
        if ext_list is not None:
            for e in list(ext_list):
                if e.get("uri") == SVG_BLIP_URI:
                    ext_list.remove(e)
            if not len(ext_list):
                blip.remove(ext_list)
        src_rect = blip_fill.find(tag(A, "srcRect"))
        if src_rect is not None:
            blip_fill.remove(src_rect)
        # Its height from its width, through any groups stretching it
        size = pic.find(f"{tag(P, 'spPr')}/{tag(A, 'xfrm')}/{tag(A, 'ext')}")
        if size is not None:
            parents = {c: p for p in root.iter() for c in p}
            scale_x = scale_y = 1.0
            el = pic
            while el in parents:
                el = parents[el]
                if el.tag != tag(P, "grpSp"):
                    continue
                xfrm = el.find(f"{tag(P, 'grpSpPr')}/{tag(A, 'xfrm')}")
                ext_el = None if xfrm is None else xfrm.find(tag(A, "ext"))
                ch_ext = None if xfrm is None else xfrm.find(tag(A, "chExt"))
                if ext_el is None or ch_ext is None:
                    continue
                ch_cx, ch_cy = (
                    int(ch_ext.get("cx", 0)),
                    int(ch_ext.get("cy", 0)),
                )
                if ch_cx and ch_cy:
                    scale_x *= int(ext_el.get("cx", 0)) / ch_cx
                    scale_y *= int(ext_el.get("cy", 0)) / ch_cy
            if scale_y:
                size.set(
                    "cy",
                    str(
                        round(
                            int(size.get("cx", 0))
                            * scale_x
                            * height
                            / (width * scale_y)
                        )
                    ),
                )
        # Images the slide no longer shows
        used = {
            v
            for el in root.iter()
            for k, v in el.attrib.items()
            if k.startswith(f"{{{R}}}")
        }
        for r in list(rels_root):
            if r.get("Type") == IMAGE_REL and r.get("Id") not in used:
                unlinked.add(target_part(slide, r.get("Target", "")))
                rels_root.remove(r)
    for part, root in edited.items():
        parts[part] = _dump(root, parts[part])
    parts["[Content_Types].xml"] = _dump(
        content_types, parts["[Content_Types].xml"]
    )
    # Drop the images nothing shows anymore
    linked = {
        target_part(rels_source(name), r.get("Target", ""))
        for name, data in parts.items()
        if name.endswith(".rels")
        for r in ET.fromstring(data)
        if r.get("TargetMode") != "External"
    }
    for part in unlinked - linked:
        parts.pop(part, None)
    # Written beside the output and moved into place, so a failure leaves
    # what was there
    output = output or source
    folder = os.path.dirname(os.path.abspath(output))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".pptx")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in parts.items():
                # Undated, so the same content makes the same file
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = 0o600 << 16
                z.writestr(info, data, zipfile.ZIP_DEFLATED)
        os.replace(tmp, output)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
