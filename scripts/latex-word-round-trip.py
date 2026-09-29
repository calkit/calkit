"""Round-trip the LaTeX/Word example: export it to Word and merge it back.

Runs on a copy of examples/latex-word, so the example itself is left alone,
with this checkout's Calkit and the LibreOffice engine, which runs on any
platform. Saves the PDFs and the Word copy for the figure, and counts what
went out and came back to results/latex-word-round-trip.json.
"""

import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import calkit.docx
import calkit.latex

OUT = Path("results/latex-word-round-trip")


def calkit_cmd(cwd: Path, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "calkit", *args], cwd=cwd, check=True
    )


def digest(paths: list[str]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(Path(p).read_bytes())
    return h.hexdigest()


def to_pdf(docx: Path, pdf: Path) -> None:
    # As LibreOffice lays it out, which is available everywhere this runs
    soffice = calkit.docx.find_soffice()
    if soffice is None:
        sys.exit("LibreOffice is needed to show the Word copy")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={Path(tmp, 'profile').as_uri()}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                tmp,
                str(docx),
            ],
            check=True,
            capture_output=True,
        )
        shutil.move(Path(tmp, docx.stem + ".pdf"), pdf)


OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    proj = Path(tmp, "latex-word")
    shutil.copytree(
        "examples/latex-word",
        proj,
        ignore=shutil.ignore_patterns(".venv", "cache", "tmp", "local"),
    )
    git = [
        "git",
        "-c",
        "user.name=Calkit",
        "-c",
        "user.email=calkit@calkit.io",
    ]
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    subprocess.run(git + ["add", "-A"], cwd=proj, check=True)
    subprocess.run(git + ["commit", "-q", "-m", "Copy"], cwd=proj, check=True)
    # LaTeX to PDF
    calkit_cmd(proj, "run")
    shutil.copy(proj / "paper" / "main.pdf", OUT / "original.pdf")
    sources = glob.glob(str(proj / "paper" / "*.tex")) + [
        str(proj / "paper" / "refs.bib")
    ]
    before = digest(sources)
    # To Word and back, with no edits
    docx = proj / "paper" / "review.docx"
    calkit_cmd(
        proj,
        "latex",
        "to-docx",
        "paper/main.pdf",
        "--engine",
        "libreoffice",
        "-o",
        "paper/review.docx",
    )
    shutil.copy(docx, OUT / "review.docx")
    to_pdf(docx, OUT / "review.pdf")
    calkit_cmd(proj, "latex", "merge-docx", "paper/review.docx")
    after = digest(sources)
    # And to PDF again, rebuilding only the paper: forcing the stage would
    # redraw its figure too, with a new timestamp inside
    (proj / "paper" / "main.pdf").unlink()
    calkit_cmd(proj, "run")
    shutil.copy(proj / "paper" / "main.pdf", OUT / "rebuilt.pdf")
    # What went out and what came back, read from the copy
    root = os.getcwd()
    os.chdir(proj)
    lines = calkit.latex.flatten("paper/main.tex")
    blks = calkit.latex.blocks(lines)
    threads = sum(
        len(calkit.latex.parse_comments(Path(p).read_text().split("\n")))
        for p in sorted({ln.path for ln in lines})
    )
    doc = calkit.docx.Document("paper/review.docx")
    sent = doc.read_original()
    assert sent is not None
    in_paragraphs = [
        m
        for p in doc.doc.iter(calkit.docx._tag(calkit.docx.W, "p"))
        for m in p.findall(calkit.docx._tag(calkit.docx.M, "oMath"))
    ]
    merges = sorted(Path(calkit.latex.LOCAL_DOCX_MERGES_DIR).glob("*.json"))
    merge = json.loads(merges[-1].read_text())
    results = {
        "engine": "libreoffice",
        "source_unchanged": before == after,
        "display_equations": {
            "source": sum(len(b.rows) for b in blks if b.display),
            "docx": len(sent.equations),
        },
        "inline_equations": {
            "source": sum(len(b.inline_math) for b in blks),
            "docx": len(in_paragraphs),
        },
        "comment_threads": {
            "source": threads,
            "docx": sum(1 for c in doc.comments if not c.parent_id),
        },
        "edits_merged": sum(
            1 for c in merge["changes"] if c["status"] == "applied"
        ),
        "comments_changed": merge["comments_added"]
        + merge["comments_updated"],
    }
    os.chdir(root)
results["pdf_unchanged"] = (OUT / "original.pdf").read_bytes() == (
    OUT / "rebuilt.pdf"
).read_bytes()
with open("results/latex-word-round-trip.json", "w") as f:
    json.dump(results, f, indent=2)
    f.write("\n")
print(json.dumps(results, indent=2))
