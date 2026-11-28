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
import shutil
import struct
import subprocess
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
# What reading or expanding a calkit from someone else may unpack, so a ZIP
# bomb can't fill the disk or memory
MAX_MANIFEST_SIZE = 10_000_000
MAX_EXPANDED_SIZE = 2_000_000_000
MAX_COMPRESSION_RATIO = 1000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Ancillary, private, and unsafe to copy, so an editor that changes the image
# drops the calkit rather than carrying a claim that no longer holds
PNG_CHUNK_TYPE = b"caLK"
PDF_ATTACHMENT_NAME = "calkit.zip"
# Tags recording calkits are named, e.g., kit/figures/plot.png/DATE-HASH
RECORD_TAG_PREFIX = "kit/"
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


class KitError(ValueError):
    """A problem with a calkit itself, rather than the file carrying it."""


def is_safe_path(path: str) -> bool:
    """Whether a path from a calkit can be written in a project: relative,
    POSIX, inside it, and not in its Git or DVC internals, which could run
    code or point at someone else's storage.
    """
    parts = path.split("/")
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or ":" in parts[0]
        or any(p in ["", ".", ".."] for p in parts)
        or ".git" in [p.lower() for p in parts]
    ):
        return False
    if path.startswith(".dvc/cache/"):
        return path.startswith(".dvc/cache/files/md5/") and path.endswith(
            ".dir"
        )
    return path != ".dvc/config.local" and not path.startswith(".dvc/tmp/")


def scrub_url(url: str) -> str:
    """Remove credentials from a URL: all of the user info for HTTP(S),
    where it's usually a token, and the password otherwise, e.g., keeping
    the 'git@' an SSH URL needs.
    """
    match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@]*)@(.*)$", url)
    if match is None:
        return url
    scheme, user_info, rest = match.groups()
    if scheme.lower().startswith("http"):
        return scheme + rest
    return f"{scheme}{user_info.split(':', 1)[0]}@{rest}"


def scrub_dvc_config(text: str) -> str:
    """Keep only what a copy of a project needs from its DVC config: the
    core settings and each remote's URL, without credentials.
    """
    import configparser

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # type: ignore[assignment,method-assign]
    config.read_string(text)
    scrubbed = configparser.ConfigParser(interpolation=None)
    scrubbed.optionxform = str  # type: ignore[assignment,method-assign]
    for section in config.sections():
        if section == "core":
            scrubbed[section] = dict(config[section])
        elif section.startswith("'remote ") and "url" in config[section]:
            scrubbed[section] = {"url": scrub_url(config[section]["url"])}
    buf = io.StringIO()
    scrubbed.write(buf)
    return buf.getvalue()


def get_stage_io(
    dvc_lock: dict, dvc_yaml: dict
) -> dict[str, dict[str, list[tuple[str, str | None]]]]:
    """Get each locked stage's dependencies and outputs as project-relative
    paths with their MD5s, since ``dvc.lock`` gives them relative to the
    stage's ``wdir``.
    """
    yaml_stages = dvc_yaml.get("stages") or {}
    result = {}
    for name, stage_lock in (dvc_lock.get("stages") or {}).items():
        yaml_stage = yaml_stages.get(name.split("@")[0]) or {}
        wdir = (
            yaml_stage.get("wdir") or (yaml_stage.get("do") or {}).get("wdir")
        ) or ""
        result[name] = {
            key: [
                (
                    posixpath.normpath(posixpath.join(wdir, item["path"])),
                    item.get("md5"),
                )
                for item in stage_lock.get(key) or []
                if isinstance(item, dict) and item.get("path")
            ]
            for key in ["deps", "outs"]
        }
    return result


def read_project_yaml(kit: bytes, name: str) -> dict:
    """Read a YAML file at the root of a calkit's project, e.g., ``dvc.lock``,
    or nothing if it has none.
    """
    import calkit

    with zipfile.ZipFile(io.BytesIO(kit)) as z:
        try:
            info = z.getinfo(PROJECT_DIR + name)
        except KeyError:
            return {}
        if info.file_size > MAX_MANIFEST_SIZE:
            raise KitError(f"Calkit's {name} is too big")
        return calkit.ryaml.load(z.read(info).decode()) or {}


def read_manifest(kit: bytes) -> Manifest:
    """Read and validate a calkit's manifest."""
    try:
        with zipfile.ZipFile(io.BytesIO(kit)) as z:
            info = z.getinfo(MANIFEST_NAME)
            if info.file_size > MAX_MANIFEST_SIZE:
                raise KitError("Calkit's manifest is too big")
            manifest_json = json.loads(z.read(info))
    except KitError:
        raise
    except KeyError:
        raise KitError(f"Calkit has no {MANIFEST_NAME}")
    except Exception as e:
        raise KitError(f"Calkit isn't a valid ZIP: {e}")
    version = (
        manifest_json.get("kit_version")
        if isinstance(manifest_json, dict)
        else None
    )
    if isinstance(version, int) and version > KIT_VERSION:
        raise KitError(
            f"Calkit is format version {version}, newer than this Calkit "
            f"reads ({KIT_VERSION}); upgrade Calkit"
        )
    try:
        return Manifest.model_validate(manifest_json)
    except Exception as e:
        raise KitError(f"Calkit's manifest is invalid: {e}")


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
    hub_url: str | None = Field(
        default=None,
        description=(
            "URL of the project's page on a Calkit hub, if it names one, "
            "where '/files?path=PATH&ref=COMMIT_SHA' shows a file at a "
            "commit."
        ),
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
        stage_io = get_stage_io(
            read_project_yaml(self.kit, "dvc.lock"),
            read_project_yaml(self.kit, "dvc.yaml"),
        )
        for out_path, out_md5 in stage_io.get(
            self.manifest.artifact.stage, {}
        ).get("outs", []):
            if out_path == self.manifest.artifact.path:
                md5 = hashlib.md5(self.artifact).hexdigest()
                return out_md5 == md5
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
            raise KitError("PNG's calkit chunk is corrupt")
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
    manifest records, if nothing was saved after the calkit.
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
    size = read_manifest(kit).artifact.size
    # Anything saved after the calkit, e.g., an annotation, is another
    # update, so the PDF without the calkit is the whole file, which no
    # longer matches
    if data[size:].count(b"%%EOF") != 1:
        return kit, data
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
    it has none, i.e., no calkit block right before its last ``</body>`` or
    ``</svg>``.
    """
    open_tag, close_tag, anchor = MARKUP_BLOCKS[fmt]
    # The file's own block is right before its last closing tag, or at the
    # end of an HTML fragment, where a nested figure's can't be
    anchor_pos = data.lower().rfind(anchor)
    if anchor_pos < 0:
        if fmt == "svg":
            return None
        anchor_pos = len(data)
    end = anchor_pos - len(close_tag)
    if end < 0 or data[end:anchor_pos] != close_tag:
        return None
    start = data.rfind(open_tag, 0, end)
    if start < 0:
        return None
    try:
        kit = base64.b64decode(data[start + len(open_tag) : end])
    except ValueError as e:
        raise KitError(f"Calkit's base64 is invalid: {e}")
    return kit, data[:start] + data[end + len(close_tag) :]


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
    # An HTML page can have an inline SVG, so its extension says first
    if ext in [".html", ".htm"]:
        return "html"
    if ext == ".svg":
        return "svg"
    if head.startswith((b"<!doctype html", b"<html")):
        return "html"
    if b"<svg" in head:
        return "svg"
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
    import calkit.hub
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
    stage_io = get_stage_io(
        lock, calkit.ryaml.load(overrides.get("dvc.yaml") or "{}") or {}
    )
    output_paths = [p for io_ in stage_io.values() for p, _ in io_["outs"]]
    dep_paths = {p for io_ in stage_io.values() for p, _ in io_["deps"]}
    # Environment specs Calkit generates, e.g., for 'calkit xr', live in
    # .calkit/envs, beside their lock files
    pruned_ck_info = calkit.ryaml.load(overrides["calkit.yaml"]) or {}
    env_dirs = {
        posixpath.dirname(Path(env["path"]).as_posix())
        for env in (pruned_ck_info.get("environments") or {}).values()
        if isinstance(env, dict)
        and isinstance(env.get("path"), str)
        and Path(env["path"]).as_posix().startswith(".calkit/")
    }
    env_paths = {
        Path(env["path"]).as_posix()
        for env in (pruned_ck_info.get("environments") or {}).values()
        if isinstance(env, dict) and isinstance(env.get("path"), str)
    }
    # Keep only DVC's core settings and remote URLs, without credentials
    if os.path.isfile(".dvc/config"):
        with open(".dvc/config") as dvc_config_file:
            overrides[".dvc/config"] = scrub_dvc_config(dvc_config_file.read())
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
                or any(p.startswith(d + "/") for d in env_dirs)
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

    def is_data(p: str) -> bool:
        # Code, config, and environment specs are the recipe, which a copy
        # can't run without
        if p in overrides or p in env_paths or p.startswith(".calkit/"):
            return False
        return calkit.provenance.is_data_path(
            p, is_file=os.path.isfile, is_dir=os.path.isdir, listdir=os.listdir
        )

    # Fill the calkit with the recipe, then the data and outputs that fit
    required = [
        p
        for p in paths
        if p in git_paths and not is_output(p) and not is_data(p)
    ]
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
    remotes = {r.name: scrub_url(r.url) for r in repo.remotes}
    # Where the project would be on its hub, from its owner and name
    try:
        hub_url: str | None = (
            calkit.hub.get_hub_url().rstrip("/")
            + "/"
            + calkit.detect_project_name()
        )
    except Exception:
        hub_url = None
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
            hub_url=hub_url,
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
    fmt = get_format(data, path)
    embed_fmt, extract_fmt = get_format_functions(fmt)
    existing = extract_fmt(data)
    if existing is not None:
        # Dropping a PDF's calkit would drop anything saved after it too
        if fmt == "pdf" and existing[1] == data:
            raise KitError(
                f"{path} was changed after its calkit was added, so it "
                "can't be replaced"
            )
        data = existing[1]
    return embed_fmt(data, kit)


def write_copy(
    path: str,
    dest_path: str,
    up_to_date: bool,
    max_size: int | None = None,
    include_data: bool = True,
    ck_info: dict | None = None,
    allow_uncommitted: bool = True,
) -> tuple[bytes, Manifest]:
    """Write a copy of an artifact with its calkit embedded, returning the
    calkit and its manifest.

    Without ``allow_uncommitted``, raises ``KitError`` before writing if any
    file in the calkit has uncommitted changes, since it then matches no
    commit.
    """
    with open(path, "rb") as f:
        data = f.read()
    fmt = get_format(data, path)
    # Base64 makes a calkit a third bigger in text formats
    if max_size is None:
        max_size = max(DEFAULT_MAX_SIZE, len(data))
    if fmt in MARKUP_BLOCKS:
        max_size = max_size * 3 // 4
    kit, manifest = build(
        path,
        up_to_date=up_to_date,
        max_size=max_size,
        include_data=include_data,
        ck_info=ck_info,
    )
    if manifest.source.uncommitted_paths and not allow_uncommitted:
        raise KitError(
            "Uncommitted changes: "
            + ", ".join(manifest.source.uncommitted_paths)
        )
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(embed(data, path, kit))
    return kit, manifest


def read(path: str) -> EmbeddedKit | None:
    """Read the calkit embedded in a file, or None if it has none.

    A file that isn't valid for its format, e.g., a truncated PNG, has
    none. Raises ``KitError`` for a calkit that can't be read.
    """
    with open(path, "rb") as f:
        data = f.read()
    try:
        fmt = get_format(data, path)
    except ValueError:
        return None
    _, extract_fmt = get_format_functions(fmt)
    try:
        extracted = extract_fmt(data)
    except KitError:
        raise
    except Exception:
        return None
    if extracted is None:
        return None
    kit, artifact = extracted
    return EmbeddedKit(kit=kit, artifact=artifact, manifest=read_manifest(kit))


def expand(path: str, dest_dir: str) -> EmbeddedKit:
    """Expand the calkit embedded in a file into a new project in
    ``dest_dir``, with the artifact in place and everything committed.

    The calkit may come from anyone, so it's checked before anything is
    written: every file must be one its manifest lists as included, with
    the same SHA-256, at a path that stays in the project and out of its
    Git and DVC internals, and it must not unpack to more than
    ``MAX_EXPANDED_SIZE``. The source project's remotes are added as Git
    remotes prefixed with ``upstream``, so its history can be fetched.
    """
    import git

    kit = read(path)
    if kit is None:
        raise KitError(f"{path} has no calkit")
    if os.path.exists(dest_dir) and os.listdir(dest_dir):
        raise ValueError(f"{dest_dir} already exists and isn't empty")
    manifest = kit.manifest
    if not is_safe_path(manifest.artifact.path):
        raise KitError(
            f"Calkit's artifact path is unsafe: {manifest.artifact.path}"
        )
    included = {f.path: f for f in manifest.files if f.included}
    # Check everything before writing anything
    files: dict[str, tuple[bytes, bool]] = {}
    total_size = 0
    with zipfile.ZipFile(io.BytesIO(kit.kit)) as z:
        for info in z.infolist():
            if not info.filename.startswith(PROJECT_DIR) or info.is_dir():
                continue
            rel_path = info.filename[len(PROJECT_DIR) :]
            if not is_safe_path(rel_path):
                raise KitError(f"Calkit has an unsafe path: {rel_path}")
            if rel_path in files:
                raise KitError(f"Calkit has {rel_path} twice")
            total_size += info.file_size
            if total_size > MAX_EXPANDED_SIZE or (
                info.file_size > 1_000_000
                and info.file_size
                > MAX_COMPRESSION_RATIO * max(info.compress_size, 1)
            ):
                raise KitError("Calkit unpacks to too much")
            content = z.read(info)
            entry = included.get(rel_path)
            if (
                entry is None
                or hashlib.sha256(content).hexdigest() != entry.sha256
            ):
                raise KitError(
                    f"Calkit's {rel_path} doesn't match its manifest"
                )
            files[rel_path] = (
                content,
                bool((info.external_attr >> 16) & 0o111),
            )
    missing = set(included) - set(files)
    if missing:
        raise KitError(
            "Calkit is missing files its manifest lists: "
            + ", ".join(sorted(missing))
        )
    files[manifest.artifact.path] = (kit.artifact, False)
    # Create the repo first, so its config and hooks are Git's own
    root = Path(dest_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    repo = git.Repo.init(root)
    dvc_paths = {f.path for f in manifest.files if f.storage == "dvc"}
    dvc_paths.add(manifest.artifact.path)
    for rel_path, (content, executable) in files.items():
        fpath = root / rel_path
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
    # Commit it, linked to where it came from
    for name, url in manifest.source.git_remotes.items():
        remote_name = "upstream" if name == "origin" else f"upstream-{name}"
        repo.create_remote(remote_name, url)
    repo.git.add("--all")
    message = f"Expand calkit from {os.path.basename(path)}"
    if manifest.source.commit_sha:
        message += f" ({manifest.source.commit_sha[:7]})"
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
    stage_io = get_stage_io(
        read_project_yaml(kit.kit, "dvc.lock"),
        read_project_yaml(kit.kit, "dvc.yaml"),
    )
    outputs = {p for io_ in stage_io.values() for p, _ in io_["outs"]}
    return [
        f.path
        for f in kit.manifest.files
        if not f.included
        and not any(f.path == o or f.path.startswith(o + "/") for o in outputs)
        and not os.path.exists(os.path.join(root, f.path))
    ]


def copy_to_clipboard(path: str, platform: str | None = None) -> None:
    """Put a file on the clipboard as a file, as copying it in a file
    manager does, so pasting into a chat or email attaches it whole.

    Copying an image's pixels instead would lose its calkit, since apps
    re-encode them.
    """
    import sys

    if platform is None:
        platform = sys.platform
    abs_path = os.path.abspath(path)
    if platform == "darwin":
        script = (
            "function run(argv) {"
            " ObjC.import('AppKit');"
            " const pb = $.NSPasteboard.generalPasteboard;"
            " pb.clearContents;"
            " pb.writeObjects($([$.NSURL.fileURLWithPath(argv[0])]));"
            " }"
        )
        cmd = ["osascript", "-l", "JavaScript", "-e", script, abs_path]
        subprocess.run(cmd, check=True, capture_output=True)
    elif platform == "win32":
        quoted = abs_path.replace("'", "''")
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Set-Clipboard -LiteralPath '{quoted}'",
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    else:
        uri = Path(abs_path).as_uri()
        for cmd in [
            ["wl-copy", "--type", "text/uri-list"],
            ["xclip", "-selection", "clipboard", "-t", "text/uri-list"],
        ]:
            if shutil.which(cmd[0]):
                subprocess.run(cmd, input=uri.encode(), check=True)
                return
        raise RuntimeError("Copying to clipboard needs wl-copy or xclip")


def get_hub_file_url(manifest: Manifest) -> str | None:
    """Get the URL of a calkit's artifact on its project's hub, at the commit
    it came from, or None if it names no hub.
    """
    from urllib.parse import urlencode

    if manifest.source.hub_url is None:
        return None
    query = {"path": manifest.artifact.path}
    if manifest.source.commit_sha:
        query["ref"] = manifest.source.commit_sha
    return f"{manifest.source.hub_url}/files?{urlencode(query)}"


def get_record_tag_name(kit: bytes, manifest: Manifest, date: str) -> str:
    """Get the name of the tag recording a calkit, e.g.,
    ``kit/figures/plot.png/2026-11-27-1a2b3c4``, which is unique to the
    calkit and valid as a Git ref.
    """
    parts = []
    for part in manifest.artifact.path.split("/"):
        part = re.sub(r"[^A-Za-z0-9._-]+", "-", part).replace("..", "-")
        part = part.lstrip(".").removesuffix(".lock") or "-"
        parts.append(part)
    kit_sha256 = hashlib.sha256(kit).hexdigest()
    return f"{RECORD_TAG_PREFIX}{'/'.join(parts)}/{date}-{kit_sha256[:7]}"


def record(kit: bytes, manifest: Manifest) -> str:
    """Record that a calkit was created, as an annotated Git tag at the
    commit it came from, returning the tag's name.

    A tag changes nothing in the project's files, keeps the commit from
    being lost to a squash or rebase, and pushing it uploads the commit
    too. Its message is a line saying what it is, then a JSON record.
    """
    import calkit
    import calkit.git

    if manifest.source.commit_sha is None:
        raise KitError("Calkit has no commit to record it at")
    created = calkit.utcnow()
    name = get_record_tag_name(kit, manifest, created.date().isoformat())
    info = {
        "artifact_path": manifest.artifact.path,
        "artifact_sha256": manifest.artifact.sha256,
        "calkit_sha256": hashlib.sha256(kit).hexdigest(),
        "commit_sha": manifest.source.commit_sha,
        "up_to_date": manifest.source.up_to_date,
        "created": created.isoformat(),
        "created_with": manifest.created_with,
    }
    message = (
        f"Calkit of {manifest.artifact.path}\n\n"
        + json.dumps(info, indent=2)
        + "\n"
    )
    calkit.git.get_repo().git.tag(
        "-a", name, manifest.source.commit_sha, "-m", message
    )
    return name


def push_record(tag_name: str, remote: str = "origin") -> None:
    """Push the tag recording a calkit, which uploads its commit too."""
    subprocess.run(
        ["git", "push", remote, f"refs/tags/{tag_name}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def get_records() -> list[dict]:
    """Get the records of calkits created from this project, newest first,
    from its tags, each with the tag's ``name``.
    """
    import calkit.git

    out = calkit.git.get_repo().git.for_each_ref(
        f"refs/tags/{RECORD_TAG_PREFIX}",
        "--sort=-creatordate",
        "--format=%(refname:strip=2)%00%(contents)%1e",
    )
    records = []
    for entry in out.split("\x1e"):
        name, _, contents = entry.strip("\n").partition("\x00")
        if not name:
            continue
        try:
            info = json.loads(contents.split("\n", 2)[2])
        except (IndexError, ValueError):
            continue
        if isinstance(info, dict):
            records.append({"name": name} | info)
    return records
