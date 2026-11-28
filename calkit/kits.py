"""Calkits: figures and documents that carry the part of a project that made
them.

A calkit, short for calculation kit, is a ZIP holding a manifest,
``calkit-kit.json``, a ``README.md`` saying what it is, and the project files
that make one artifact, under ``project/``. It's embedded in a copy of the
artifact, so wherever the file goes, what made it goes with it. See
https://docs.calkit.org/calkits for the format.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import io
import json
import os
import posixpath
import re
import struct
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KIT_VERSION = 1
MANIFEST_NAME = "calkit-kit.json"
README_NAME = "README.md"
PROJECT_DIR = "project/"
MEDIA_TYPE = "application/vnd.calkit+zip"
DOCS_URL = "https://docs.calkit.org/calkits"
SCHEMA_URL = "https://docs.calkit.org/schemas/calkit-kit.json"
SCHEMA_REPO_PATH = "docs/schemas/calkit-kit.json"
# A calkit may grow its artifact to this size, or double it if that's
# bigger, with files left out smallest first once it's full
DEFAULT_MAX_SIZE = 1_000_000
# A fixed timestamp keeps a calkit's bytes the same for the same project state
ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Ancillary, private, and unsafe to copy, so an editor that changes the image
# drops the calkit rather than carrying a claim that no longer holds
PNG_CHUNK_TYPE = b"caLK"
PDF_ATTACHMENT_NAME = "calkit.zip"
# What wraps a calkit's base64 in text formats, by format, and the tag it
# goes before
MARKUP_COMMENT = (
    b"<!-- Calkit: what made this file; " + DOCS_URL.encode() + b" -->"
)
MARKUP_BLOCKS = {
    "html": (
        MARKUP_COMMENT
        + b'<script type="application/vnd.calkit+zip;base64" id="calkit">',
        b"</script>",
        b"</body>",
    ),
    "svg": (
        b'<metadata id="calkit">'
        + MARKUP_COMMENT
        + b'<calkit xmlns="https://docs.calkit.org/calkits" version="1" '
        b'encoding="base64">',
        b"</calkit></metadata>",
        b"</svg>",
    ),
}


class KitArtifact(BaseModel):
    path: str = Field(description="Path of the artifact in the project.")
    size: int = Field(description="Size in bytes, without the calkit.")
    sha256: str = Field(
        description="SHA-256 of the artifact, without the calkit."
    )
    stage: str = Field(description="Name of the pipeline stage that makes it.")


class KitSource(BaseModel):
    name: str | None = Field(default=None, description="Name of the project.")
    title: str | None = Field(
        default=None, description="Title of the project."
    )
    git_remotes: dict[str, str] = Field(
        default_factory=dict,
        description="Git remote URLs by name, without credentials.",
    )
    commit_sha: str | None = Field(
        default=None, description="Git commit the calkit was made from."
    )
    uncommitted_paths: list[str] = Field(
        default_factory=list,
        description="Files in the calkit with changes not in that commit.",
    )
    up_to_date: bool = Field(
        description=(
            "Whether the artifact's stage, and every stage upstream of it, "
            "was up to date when the calkit was made."
        )
    )


class KitFile(BaseModel):
    path: str = Field(description="Path in the project.")
    size: int = Field(description="Size in bytes.")
    storage: Literal["git", "dvc"] = Field(
        description="Where the project keeps the file."
    )
    included: bool = Field(
        description=(
            "Whether the file is in the calkit, under 'project/'. Files left "
            "out can be fetched from the project's DVC remote, or remade by "
            "running the pipeline."
        )
    )
    sha256: str | None = Field(
        default=None,
        description="SHA-256 of the file, if it's in the calkit.",
    )
    md5: str | None = Field(
        default=None,
        description="DVC's MD5 of the file, for fetching it from DVC storage.",
    )


class KitProvenanceGap(BaseModel):
    path: str = Field(description="Path nothing records the origin of.")
    unchecked: bool = Field(
        default=False,
        description=(
            "Whether it's recorded as imported, but from somewhere nobody "
            "else can check, e.g., a folder on someone's machine."
        ),
    )
    message: str = Field(description="How it leads to the artifact.")


class Manifest(BaseModel):
    """What a calkit holds and where it came from."""

    model_config = ConfigDict(populate_by_name=True)

    schema_url: str = Field(
        default=SCHEMA_URL,
        alias="$schema",
        description="URL of this schema, which says where to learn more.",
    )
    kit_version: int = Field(
        default=KIT_VERSION, description="Calkit format version."
    )
    created_with: str = Field(description="Tool and version that made it.")
    artifact: KitArtifact
    source: KitSource
    files: list[KitFile] = Field(
        description="Files the artifact's pipeline uses, in the calkit or not."
    )
    provenance_gaps: list[KitProvenanceGap] = Field(
        default_factory=list,
        description=(
            "Inputs upstream of the artifact that no stage makes and that "
            "have no recorded origin, e.g., an import or who created them."
        ),
    )


@dataclasses.dataclass
class EmbeddedKit:
    """A calkit read from an artifact."""

    kit: bytes
    artifact: bytes
    manifest: Manifest

    @property
    def artifact_unchanged(self) -> bool:
        """Whether the artifact is the one the calkit was made for."""
        sha256 = hashlib.sha256(self.artifact).hexdigest()
        return sha256 == self.manifest.artifact.sha256

    @property
    def matches_pipeline(self) -> bool | None:
        """Whether the artifact is the output the calkit's ``dvc.lock``
        records, or None if it records none.
        """
        import calkit

        with zipfile.ZipFile(io.BytesIO(self.kit)) as z:
            try:
                lock = calkit.ryaml.load(
                    z.read(PROJECT_DIR + "dvc.lock").decode()
                )
            except KeyError:
                return None
        stage = (lock.get("stages") or {}).get(self.manifest.artifact.stage)
        for out in (stage or {}).get("outs") or []:
            if out.get("path") == self.manifest.artifact.path:
                md5 = hashlib.md5(self.artifact).hexdigest()
                return bool(out.get("md5") == md5)
        return None


def generate_schema_json() -> str:
    """Generate the JSON schema for calkit manifests as formatted JSON."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URL,
        **Manifest.model_json_schema(),
        "title": "Calkit manifest",
        "description": (
            "The calkit-kit.json at the root of a calkit, the ZIP embedded "
            f"in an artifact holding what made it. See {DOCS_URL}"
        ),
    }
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def get_png_chunk_spans(data: bytes) -> list[tuple[int, int, bytes]]:
    """Get the start, end, and type of each chunk of a PNG, up to and
    including IEND.
    """
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Not a PNG")
    spans = []
    pos = len(PNG_SIGNATURE)
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        chunk_type = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("PNG is truncated")
        spans.append((pos, end, chunk_type))
        pos = end
        if chunk_type == b"IEND":
            break
    return spans


def embed_png(data: bytes, kit: bytes) -> bytes:
    """Return a copy of a PNG with a calkit chunk inserted before IEND, where
    removing it restores the original bytes exactly.
    """
    iend_start = next(
        (s for s, _, t in get_png_chunk_spans(data) if t == b"IEND"), None
    )
    if iend_start is None:
        raise ValueError("PNG has no IEND chunk")
    chunk = (
        struct.pack(">I", len(kit))
        + PNG_CHUNK_TYPE
        + kit
        + struct.pack(">I", zlib.crc32(PNG_CHUNK_TYPE + kit))
    )
    return data[:iend_start] + chunk + data[iend_start:]


def extract_png(data: bytes) -> tuple[bytes, bytes] | None:
    """Get a PNG's calkit and the PNG without it, or None if it has none."""
    for start, end, chunk_type in get_png_chunk_spans(data):
        if chunk_type != PNG_CHUNK_TYPE:
            continue
        kit = data[start + 8 : end - 4]
        (crc,) = struct.unpack(">I", data[end - 4 : end])
        if crc != zlib.crc32(PNG_CHUNK_TYPE + kit):
            raise ValueError("PNG's calkit chunk is corrupt")
        return kit, data[:start] + data[end:]
    return None


def embed_pdf(data: bytes, kit: bytes) -> bytes:
    """Return a copy of a PDF with a calkit attached.

    The attachment is appended as an incremental update, so viewers list it
    with the document's attachments, and truncating to the original size
    restores the original bytes exactly.
    """
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    pdf = pdfium.PdfDocument(data)
    try:
        attachment = pdf.new_attachment(PDF_ATTACHMENT_NAME)
        attachment.set_data(kit)
        buf = io.BytesIO()
        pdf.save(buf, flags=pdfium_c.FPDF_INCREMENTAL)
    finally:
        pdf.close()
    out = buf.getvalue()
    if not out.startswith(data):
        raise ValueError("Attaching calkit rewrote the PDF")
    return out


def extract_pdf(data: bytes) -> tuple[bytes, bytes] | None:
    """Get a PDF's calkit and the PDF without it, or None if it has none.

    The PDF without its calkit is the prefix with the size the calkit's
    manifest records.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        kit = None
        for i in range(pdf.count_attachments()):
            attachment = pdf.get_attachment(i)
            if attachment.get_name() == PDF_ATTACHMENT_NAME:
                kit = bytes(attachment.get_data())
                break
    finally:
        pdf.close()
    if kit is None:
        return None
    with zipfile.ZipFile(io.BytesIO(kit)) as z:
        size = json.loads(z.read(MANIFEST_NAME))["artifact"]["size"]
    return kit, data[:size]


def embed_markup(data: bytes, kit: bytes, fmt: str) -> bytes:
    """Return a copy of an HTML or SVG file with a calkit inserted as base64
    before its last closing tag, i.e., ``</body>`` or ``</svg>``.

    An HTML fragment without ``</body>`` gets it at the end.
    """
    open_tag, close_tag, anchor = MARKUP_BLOCKS[fmt]
    pos = data.lower().rfind(anchor)
    if pos < 0:
        if fmt == "svg":
            raise ValueError("SVG has no closing </svg> tag")
        pos = len(data)
    block = open_tag + b"\n" + base64.encodebytes(kit) + close_tag
    return data[:pos] + block + data[pos:]


def extract_markup(data: bytes, fmt: str) -> tuple[bytes, bytes] | None:
    """Get an HTML or SVG file's calkit and the file without it, or None if
    it has none.
    """
    open_tag, close_tag, _ = MARKUP_BLOCKS[fmt]
    match = re.search(
        re.escape(open_tag) + rb"(.*?)" + re.escape(close_tag), data, re.S
    )
    if match is None:
        return None
    kit = base64.b64decode(match.group(1))
    return kit, data[: match.start()] + data[match.end() :]


def get_format(data: bytes, path: str) -> str:
    """Get the format of a file a calkit can go in, from its contents and,
    for text formats, its extension.
    """
    ext = os.path.splitext(path)[-1].lower()
    head = data[:1024].lstrip().lower()
    if data.startswith(PNG_SIGNATURE):
        return "png"
    if data.startswith(b"%PDF-"):
        return "pdf"
    if ext == ".svg" or b"<svg" in head:
        return "svg"
    if ext in [".html", ".htm"] or head.startswith(
        (b"<!doctype html", b"<html")
    ):
        return "html"
    raise ValueError(
        f"Can't embed a calkit in {path}; supported types: PNG, PDF, SVG, HTML"
    )


def get_format_functions(
    fmt: str,
) -> tuple[
    Callable[[bytes, bytes], bytes],
    Callable[[bytes], tuple[bytes, bytes] | None],
]:
    """Get the functions that embed a calkit in and extract one from a
    format.
    """
    if fmt == "png":
        return embed_png, extract_png
    if fmt == "pdf":
        return embed_pdf, extract_pdf
    return (
        lambda data, kit: embed_markup(data, kit, fmt),
        lambda data: extract_markup(data, fmt),
    )


def write_zip(files: dict[str, tuple[bytes, bool]]) -> bytes:
    """Write a deterministic ZIP from paths mapped to content and whether
    they're executable.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, (content, executable) in files.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if executable else 0o644) << 16
            z.writestr(info, content)
    return buf.getvalue()


def make_readme(manifest: Manifest) -> str:
    """Make the README that says what a calkit is, for anyone who opens
    the ZIP without Calkit.
    """
    source = manifest.source
    origin = source.name or "a project"
    remote = source.git_remotes.get("origin") or next(
        iter(source.git_remotes.values()), None
    )
    if source.commit_sha:
        origin += f" at commit {source.commit_sha}"
    if remote:
        origin += f" of {remote}"
    name = os.path.basename(manifest.artifact.path)
    return (
        f"# Calkit for {manifest.artifact.path}\n\n"
        "This is a calkit, short for calculation kit: the part of a project "
        f"that makes {manifest.artifact.path}, packed inside {name}.\n"
        f"It came from {origin}.\n"
        f"`{MANIFEST_NAME}` lists what's here and what was left out, and "
        "`project/` holds the files.\n\n"
        "With Calkit (https://calkit.org) installed:\n\n"
        "```sh\n"
        f"calkit describe {name}    # What made it, and whether it changed\n"
        f"calkit kit expand {name}  # Unpack it into a project\n"
        f"calkit kit run {name}     # Unpack it, rerun it, and compare\n"
        "```\n\n"
        f"See {DOCS_URL}\n"
    )


def build(
    path: str,
    up_to_date: bool,
    max_size: int | None = None,
    include_data: bool = True,
    ck_info: dict | None = None,
) -> tuple[bytes, Manifest]:
    """Build the calkit for an artifact the pipeline makes.

    The calkit holds the project pruned to the artifact's stage and those
    upstream of it, as a release with ``--pipeline`` does. Files kept in Git
    that no stage makes, e.g., scripts and environment specs, are always
    included. Files kept with DVC and stage outputs are included smallest
    first, inputs before outputs, while the calkit fits in ``max_size``,
    which defaults to the artifact's size or ``DEFAULT_MAX_SIZE``, whichever
    is bigger. ``up_to_date`` is recorded as given, since the caller has
    usually just checked the pipeline.
    """
    import copy

    import calkit
    import calkit.dvc
    import calkit.git
    import calkit.pipeline
    import calkit.provenance
    import calkit.releases

    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    path = posixpath.normpath(Path(path).as_posix())
    stage = calkit.pipeline.get_stage_for_output(path, ck_info)
    if stage is None:
        raise ValueError(f"No pipeline stage makes {path}")
    with open(path, "rb") as f:
        artifact_data = f.read()
    if max_size is None:
        max_size = max(DEFAULT_MAX_SIZE, len(artifact_data))
    overrides, paths = calkit.releases.prune_for_stage(
        copy.deepcopy(ck_info), stage
    )
    lock = calkit.ryaml.load(overrides.get("dvc.lock") or "{}") or {}
    stage_locks = (lock.get("stages") or {}).values()
    output_paths = [
        Path(out["path"]).as_posix()
        for stage_lock in stage_locks
        for out in stage_lock.get("outs") or []
    ]
    dep_paths = {
        Path(dep["path"]).as_posix()
        for stage_lock in stage_locks
        for dep in stage_lock.get("deps") or []
    }
    # Keep the stage run records for the calkit's stages, without the ID of
    # the machine they ran on
    runs_path = ".calkit/stage-runs.json"
    if os.path.isfile(runs_path):
        with open(runs_path) as runs_file:
            runs = json.load(runs_file)
        runs = {
            k: v for k, v in runs.items() if k in (lock.get("stages") or {})
        }
        for run in runs.values():
            if isinstance(run.get("system"), dict):
                run["system"].pop("machine_id", None)
        overrides[runs_path] = json.dumps(runs, indent=2) + "\n"
    # Leave out the DVC cache, besides directory listings, since files come
    # in the workspace; what describes this machine; and anything in .calkit
    # a stage doesn't read or need to run, e.g., Overleaf sync state or
    # comments. The artifact itself carries the calkit.
    calkit_prefixes = tuple(
        f".calkit/{d}/"
        for d in ["env-locks", "imports", "zip", "stage-commands"]
    )

    def is_kept(p: str) -> bool:
        if p in [path, ".dvc/config.local"] or p.startswith(".dvc/tmp/"):
            return False
        if p.startswith(".dvc/cache/"):
            return p.endswith(".dir")
        if p.startswith(".calkit/"):
            return (
                p in dep_paths
                or p in overrides
                or p.startswith(calkit_prefixes)
                or any(p.startswith(d + "/") for d in dep_paths)
            )
        return True

    paths = sorted(
        {Path(p).as_posix() for p in paths if is_kept(Path(p).as_posix())}
        | set(overrides)
    )
    # Work out where each file is kept
    repo = calkit.git.get_repo()
    git_paths = (
        set(repo.git.ls_files().splitlines())
        | set(overrides)
        | {p for p in paths if p.startswith(".dvc/cache/")}
    )
    dvc_files = {
        Path(f["path"]).as_posix(): f for f in calkit.dvc.list_files()
    }

    def is_output(p: str) -> bool:
        return any(p == o or p.startswith(o + "/") for o in output_paths)

    def read(p: str) -> bytes:
        if p in overrides:
            return overrides[p].encode()
        with open(p, "rb") as f:
            return f.read()

    # Fill the calkit with what's always needed, then what fits
    required = [p for p in paths if p in git_paths and not is_output(p)]
    optional = [p for p in paths if p not in required]
    included = {p: read(p) for p in required}
    used = sum(len(zlib.compress(c)) for c in included.values())
    # A file DVC tracks may not be on this machine, so can't be included
    sizes = {
        p: len(included[p])
        if p in included
        else os.path.getsize(p)
        if os.path.isfile(p)
        else int((dvc_files.get(p) or {}).get("size") or 0)
        for p in paths
    }
    for p in sorted(optional, key=lambda p: (is_output(p), sizes[p], p)):
        # Compression rarely beats 20x, so don't read what can't fit
        if (
            not include_data
            or not os.path.isfile(p)
            or sizes[p] > 20 * (max_size - used)
        ):
            continue
        content = read(p)
        compressed_size = len(zlib.compress(content))
        if used + compressed_size <= max_size:
            included[p] = content
            used += compressed_size
    # Say what the calkit holds and where it came from, including what's
    # uncommitted in Git, or for what DVC tracks, differs from what it
    # recorded
    uncommitted = set()
    for line in repo.git.status(
        "--porcelain", "--untracked-files=no"
    ).splitlines():
        uncommitted.add(line[3:].split(" -> ")[-1].strip('"'))
    for p, content in included.items():
        recorded_md5 = (dvc_files.get(p) or {}).get("md5")
        if recorded_md5 and hashlib.md5(content).hexdigest() != recorded_md5:
            uncommitted.add(p)
    remotes = {
        r.name: re.sub(r"^(https?://)[^/@]+@", r"\1", r.url)
        for r in repo.remotes
    }
    files = []
    for p in paths:
        dvc_file = dvc_files.get(p)
        files.append(
            KitFile(
                path=p,
                size=sizes[p],
                storage="dvc" if dvc_file and p not in git_paths else "git",
                included=p in included,
                sha256=(
                    hashlib.sha256(included[p]).hexdigest()
                    if p in included
                    else None
                ),
                md5=dvc_file.get("md5") if dvc_file else None,
            )
        )
    manifest = Manifest(
        created_with=f"calkit {calkit.__version__}",
        artifact=KitArtifact(
            path=path,
            size=len(artifact_data),
            sha256=hashlib.sha256(artifact_data).hexdigest(),
            stage=stage,
        ),
        source=KitSource(
            name=ck_info.get("name") or os.path.basename(repo.working_dir),
            title=ck_info.get("title"),
            git_remotes=remotes,
            commit_sha=repo.head.commit.hexsha
            if repo.head.is_valid()
            else None,
            uncommitted_paths=sorted(uncommitted & (set(paths) | {path})),
            up_to_date=up_to_date,
        ),
        files=files,
        provenance_gaps=[
            KitProvenanceGap(
                path=gap.path, unchecked=gap.unchecked, message=str(gap)
            )
            for gap in calkit.provenance.find_project_provenance_gaps(
                [path], ck_info=ck_info
            )
        ],
    )
    zip_files = {
        MANIFEST_NAME: (
            manifest.model_dump_json(
                indent=2, exclude_none=True, by_alias=True
            ).encode(),
            False,
        ),
        README_NAME: (make_readme(manifest).encode(), False),
    }
    for p, content in included.items():
        executable = p not in overrides and os.access(p, os.X_OK)
        zip_files[PROJECT_DIR + p] = (content, executable)
    return write_zip(zip_files), manifest


def embed(data: bytes, path: str, kit: bytes) -> bytes:
    """Return a copy of an artifact's contents with a calkit embedded,
    replacing any it already has.
    """
    embed_fmt, extract_fmt = get_format_functions(get_format(data, path))
    existing = extract_fmt(data)
    if existing is not None:
        data = existing[1]
    return embed_fmt(data, kit)


def write_copy(
    path: str,
    dest_path: str,
    up_to_date: bool,
    max_size: int | None = None,
    include_data: bool = True,
    ck_info: dict | None = None,
) -> Manifest:
    """Write a copy of an artifact with its calkit embedded."""
    kit, manifest = build(
        path,
        up_to_date=up_to_date,
        max_size=max_size,
        include_data=include_data,
        ck_info=ck_info,
    )
    with open(path, "rb") as f:
        data = f.read()
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(embed(data, path, kit))
    return manifest


def read(path: str) -> EmbeddedKit | None:
    """Read the calkit embedded in a file, or None if it has none."""
    with open(path, "rb") as f:
        data = f.read()
    try:
        fmt = get_format(data, path)
    except ValueError:
        return None
    _, extract_fmt = get_format_functions(fmt)
    extracted = extract_fmt(data)
    if extracted is None:
        return None
    kit, artifact = extracted
    with zipfile.ZipFile(io.BytesIO(kit)) as z:
        manifest = Manifest.model_validate(json.loads(z.read(MANIFEST_NAME)))
    return EmbeddedKit(kit=kit, artifact=artifact, manifest=manifest)


def expand(path: str, dest_dir: str) -> EmbeddedKit:
    """Expand the calkit embedded in a file into a new project in
    ``dest_dir``, with the artifact in place and everything committed.

    The source project's remotes are added as Git remotes prefixed with
    ``upstream``, so its history can be fetched.
    """
    import git

    kit = read(path)
    if kit is None:
        raise ValueError(f"{path} has no calkit")
    if os.path.exists(dest_dir) and os.listdir(dest_dir):
        raise ValueError(f"{dest_dir} already exists and isn't empty")
    root = Path(dest_dir).resolve()
    dvc_paths = {f.path for f in kit.manifest.files if f.storage == "dvc"}
    dvc_paths.add(kit.manifest.artifact.path)

    def write(rel_path: str, content: bytes, executable: bool = False) -> None:
        fpath = (root / rel_path).resolve()
        if not fpath.is_relative_to(root):
            raise ValueError(
                f"Calkit has a path outside the project: {rel_path}"
            )
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_bytes(content)
        if executable:
            fpath.chmod(0o755)
        # Put what DVC tracks in its cache too, so DVC sees it as committed
        if rel_path in dvc_paths:
            md5 = hashlib.md5(content).hexdigest()
            cache_path = root / ".dvc/cache/files/md5" / md5[:2] / md5[2:]
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(content)

    # Write the project, then the artifact the calkit came in
    with zipfile.ZipFile(io.BytesIO(kit.kit)) as z:
        for info in z.infolist():
            if not info.filename.startswith(PROJECT_DIR) or info.is_dir():
                continue
            write(
                info.filename[len(PROJECT_DIR) :],
                z.read(info),
                executable=bool((info.external_attr >> 16) & 0o111),
            )
    write(kit.manifest.artifact.path, kit.artifact)
    # Commit it, linked to where it came from
    repo = git.Repo.init(root)
    for name, url in kit.manifest.source.git_remotes.items():
        remote_name = "upstream" if name == "origin" else f"upstream-{name}"
        repo.create_remote(remote_name, url)
    repo.git.add("--all")
    message = f"Expand calkit from {os.path.basename(path)}"
    if kit.manifest.source.commit_sha:
        message += f" ({kit.manifest.source.commit_sha[:7]})"
    try:
        repo.git.commit("-m", message)
    except git.GitCommandError:
        # Most likely no Git identity on this machine, so leave it staged
        pass
    return kit


def get_missing_inputs(kit: EmbeddedKit, root: str) -> list[str]:
    """Get the files an expanded calkit's stages read that aren't there,
    i.e., inputs left out of it and not yet pulled.
    """
    import calkit

    with zipfile.ZipFile(io.BytesIO(kit.kit)) as z:
        try:
            lock = calkit.ryaml.load(z.read(PROJECT_DIR + "dvc.lock").decode())
        except KeyError:
            lock = {}
    outputs = {
        out["path"]
        for stage in (lock.get("stages") or {}).values()
        for out in stage.get("outs") or []
    }
    return [
        f.path
        for f in kit.manifest.files
        if not f.included
        and not any(f.path == o or f.path.startswith(o + "/") for o in outputs)
        and not os.path.exists(os.path.join(root, f.path))
    ]
