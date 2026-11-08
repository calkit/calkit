"""Exporting data and artifacts from various apps, e.g., a PNG from an
Inkscape SVG.

An app that can export from the command line does it as the pipeline runs,
in a stage of its own kind. Anything else is a manual step. The apps that
can are listed here once, so the CLI, the hub, and anything built on them
agree on which they are.
"""

from __future__ import annotations

import dataclasses
import os
import re


@dataclasses.dataclass
class Exporter:
    """An app that exports as the pipeline runs, and its stage kind."""

    # As a key, e.g., in 'inkscape_version'
    name: str
    kind: str
    app: str
    # What it exports from, as a person would say it
    source_desc: str
    source_exts: frozenset[str]
    export_exts: frozenset[str]
    # Its executable, by name on PATH, or where its installer puts it
    executables: list[str]
    # The app the source is made in, when it's another, e.g., PowerPoint
    source_app: str | None = None

    def find_executable(self) -> str | None:
        """Its executable here, if it's installed."""
        import shutil

        for candidate in self.executables:
            found = shutil.which(candidate)
            if found:
                return found
            # A macOS app bundle is a folder
            if os.path.isabs(candidate) and os.path.exists(candidate):
                return candidate
        return None

    def version(self) -> str | None:
        """The version installed here, if it's installed and says."""
        import subprocess

        from calkit.core import extract_version

        exe = self.find_executable()
        if exe is None:
            return None
        # Apps that don't answer '--version' say it in their bundle or file
        if exe.endswith(".app"):
            import plistlib

            try:
                with open(
                    os.path.join(exe, "Contents", "Info.plist"), "rb"
                ) as f:
                    version = plistlib.load(f).get(
                        "CFBundleShortVersionString"
                    )
                return str(version) if version else None
            except (OSError, plistlib.InvalidFileException):
                return None
        if exe.lower().endswith("powerpnt.exe"):
            try:
                import win32api  # type: ignore[import-untyped]

                info = win32api.GetFileVersionInfo(exe, "\\")
            except Exception:
                return None
            ms, ls = info["FileVersionMS"], info["FileVersionLS"]
            return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        try:
            result = subprocess.run(
                [exe, "--version"], capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return extract_version(result.stdout or result.stderr or "")

    def check(self, source: str, output: str) -> None:
        """Raise ``ValueError`` unless it can export ``source`` to
        ``output``.
        """
        if os.path.splitext(source)[1].lower() not in self.source_exts:
            raise ValueError(
                f"{self.app} exports from {self.source_desc}, not '{source}'"
            )
        if os.path.splitext(output)[1].lower() not in self.export_exts:
            raise ValueError(
                f"{self.app} can export to "
                f"{', '.join(sorted(self.export_exts))}, not '{output}'"
            )


INKSCAPE = Exporter(
    name="inkscape",
    kind="inkscape-export",
    app="Inkscape",
    source_desc="an SVG",
    source_exts=frozenset({".svg"}),
    export_exts=frozenset({".png", ".pdf", ".eps", ".ps"}),
    executables=[
        "inkscape",
        "/Applications/Inkscape.app/Contents/MacOS/inkscape",
        r"C:\Program Files\Inkscape\bin\inkscape.exe",
    ],
)
GIMP = Exporter(
    name="gimp",
    kind="gimp-export",
    app="GIMP",
    source_desc="an XCF file",
    source_exts=frozenset({".xcf"}),
    export_exts=frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff"}),
    # The console binary, since the plain 'gimp' on macOS opens a window
    # and ignores batch flags
    executables=[
        "gimp-console",
        "gimp-console-3",
        "gimp-console-2.10",
        "/Applications/GIMP.app/Contents/MacOS/gimp-console",
        r"C:\Program Files\GIMP 3\bin\gimp-console-3.0.exe",
        r"C:\Program Files\GIMP 2\bin\gimp-console-2.10.exe",
    ],
)
# Slides can be exported by either; which one is up to the environment
LIBREOFFICE = Exporter(
    name="libreoffice",
    kind="pptx-export",
    app="LibreOffice",
    source_desc="a PowerPoint file",
    source_exts=frozenset({".pptx", ".pptm"}),
    export_exts=frozenset({".pdf", ".png"}),
    executables=[
        "soffice",
        "libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
    ],
    source_app="PowerPoint",
)
POWERPOINT = Exporter(
    name="powerpoint",
    kind="pptx-export",
    app="PowerPoint",
    source_desc="a PowerPoint file",
    source_exts=frozenset({".pptx", ".pptm"}),
    export_exts=frozenset({".pdf", ".png"}),
    executables=[
        "/Applications/Microsoft PowerPoint.app",
        r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE",
    ],
)
# What a Docker environment for exporting slides runs, LibreOffice and
# fonts pinned together, and the release a new one starts from
LIBREOFFICE_IMAGE = "ghcr.io/calkit/libreoffice"
LIBREOFFICE_IMAGE_VERSION = "0.1.0"


def exporters() -> list[Exporter]:
    return [INKSCAPE, GIMP, LIBREOFFICE, POWERPOINT]


def get_slide_exporter(
    env_name: str = "_system", ck_info: dict | None = None
) -> tuple[Exporter, str | None]:
    """The app that exports slides in an environment, and the Docker
    environment it runs in, if it runs in one.

    A Docker environment runs LibreOffice, and a system environment
    whichever of PowerPoint and LibreOffice it requires. ``_system`` takes
    whichever is installed, which can differ from machine to machine.
    """
    from calkit.core import _normalize_requirement

    if env_name == "_system":
        for exporter in (LIBREOFFICE, POWERPOINT):
            if exporter.find_executable() is not None:
                return exporter, None
        raise ValueError(
            "Exporting slides needs LibreOffice or PowerPoint installed"
        )
    env = (ck_info or {}).get("environments", {}).get(env_name)
    if env is None:
        raise ValueError(f"There's no environment named '{env_name}'")
    kind = env.get("kind")
    if kind == "docker":
        return LIBREOFFICE, env_name
    if kind == "system":
        apps = {"powerpoint": POWERPOINT, "libreoffice": LIBREOFFICE}
        apps["soffice"] = LIBREOFFICE
        for req in env.get("requirements") or []:
            req = _normalize_requirement(req)
            name = str(req.get("name") or "").lower()
            if req.get("kind") == "app" and name in apps:
                return apps[name], None
        raise ValueError(
            f"Environment '{env_name}' requires neither PowerPoint nor "
            "LibreOffice, so it doesn't say which exports slides"
        )
    raise ValueError(
        f"Slides can't be exported in a {kind} environment like "
        f"'{env_name}'; use a Docker environment with the "
        f"{LIBREOFFICE_IMAGE} image, or a system environment that "
        "requires PowerPoint or LibreOffice"
    )


def get_slide_environment(ck_info: dict) -> tuple[str, dict | None]:
    """The environment a slide is exported in unless its stage says, and
    what to add to the project for it, if it isn't there yet.

    It's one running Calkit's LibreOffice image, so a slide exports the same
    on any machine with Docker, GitHub's included.
    """
    envs = ck_info.get("environments") or {}
    for name, env in envs.items():
        image = str((env or {}).get("image") or "")
        if (env or {}).get("kind") == "docker" and (
            image == LIBREOFFICE_IMAGE
            or image.startswith(
                (LIBREOFFICE_IMAGE + ":", LIBREOFFICE_IMAGE + "@")
            )
        ):
            return name, None
    name, n = "libreoffice", 2
    while name in envs:
        name, n = f"libreoffice-{n}", n + 1
    return name, {
        "kind": "docker",
        "image": f"{LIBREOFFICE_IMAGE}:{LIBREOFFICE_IMAGE_VERSION}",
    }


def get_slide_exporter_version(
    exporter: Exporter, docker_env: str | None = None
) -> str | None:
    """The version of the app that exports slides, which in a Docker
    environment is the one in its image.
    """
    import subprocess

    from calkit.core import extract_version

    if docker_env is None:
        return exporter.version()
    try:
        result = subprocess.run(
            ["calkit", "xenv", "-n", docker_env, "--no-check", "--"]
            + ["soffice", "--version"],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return extract_version(result.stdout or "")


def exporter_for(
    source: str, output: str, app: str | None = None
) -> Exporter | None:
    """The app that can export ``output`` from ``source`` as the pipeline
    runs, if any.

    One a person names has to be that app, or the one the source is made
    in: an SVG exported with Illustrator is a manual step, even though
    Inkscape could do it, but a slide exported with PowerPoint isn't.
    """
    source_ext = os.path.splitext(source)[1].lower()
    output_ext = os.path.splitext(output)[1].lower()
    named = (app or "").strip().lower()
    for exporter in exporters():
        if (
            source_ext in exporter.source_exts
            and output_ext in exporter.export_exts
            and named
            in ("", exporter.app.lower(), (exporter.source_app or "").lower())
        ):
            return exporter
    return None


def export_stage(source: str, output: str, app: str | None = None) -> dict:
    """The stage exporting ``output`` from ``source``, as written in
    calkit.yaml.

    An app that can does it as the pipeline runs. Otherwise it's a manual
    step, which opens ``source`` in ``app`` if one is named.
    """
    exporter = exporter_for(source, output, app=app)
    if exporter is not None:
        stage: dict = {
            "kind": exporter.kind,
            "source_path": source,
            "outputs": [output],
        }
        # A figure from a deck is one slide, the first until someone says
        if exporter.kind == "pptx-export":
            stage["outputs"] = [{"path": output, "slide": 1}]
        return stage
    app = (app or "").strip()
    stage = {
        "kind": "manual-step",
        "message": (
            f"In {app}, export {output} from {source}"
            if app
            else f"Export {output} from {source}"
        ),
        "inputs": [source],
        "outputs": [output],
    }
    if app:
        stage["open"] = {"app": app, "path": source}
    return stage


def export_stage_name(output: str) -> str:
    """A name for the stage exporting ``output``, e.g., ``export-setup``."""
    stem = os.path.splitext(os.path.basename(output))[0]
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return f"export-{slug or 'figure'}"
