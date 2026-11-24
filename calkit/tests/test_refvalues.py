"""Tests for ``calkit.refvalues``."""

import json
import os
from pathlib import Path

import pytest

import calkit.refvalues as rv


def write_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Write a minimal PDF, one line of text per string, in Helvetica,
    which every PDF reader has.
    """

    def escape(text: str) -> str:
        return (
            text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        )

    objects: list[bytes] = []
    n_pages = len(pages)
    # 1 is the catalog, 2 the page tree, 3 the font, then a page and its
    # content for each page
    page_ids = [4 + 2 * i for i in range(n_pages)]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    )
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    for i, lines in enumerate(pages):
        content = "BT /F1 11 Tf 72 740 Td 14 TL\n"
        content += "".join(f"({escape(line)}) Tj T*\n" for line in lines)
        content += "ET"
        stream = content.encode("cp1252")
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {page_ids[i] + 1} 0 R >>"
            ).encode()
        )
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        )
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


@pytest.mark.parametrize(
    "value, text, found",
    [
        (0.1, "noise of 0.1 was", True),
        (0.1, "noise of 0.10 was", True),
        (0.1, "noise of .1 was", True),
        (0.1, "noise of 0.15 was", False),
        (0.1, "noise of 10.1 was", False),
        (0.1, "see section 2.0.1", False),
        ("12.5%", "about 12.5 % of runs", True),
        ("12.5%", "about 12.5 of runs", False),
        (10000, "trained on 10,000 orbits", True),
        (10000, "trained on 10000 orbits", True),
        (10000, "trained on 100000 orbits", False),
        (-1.9, "scales as r−1.9 here", False),
        (-1.9, "slope of −1.9 here", True),
        (0.001, "a rate of 10−3 per step", False),
        (1e-8, "tolerances of 10−8 and", True),
        (1e-8, "tolerances of 1e-8 and", True),
        (2.5e-8, "a value of 2.5 × 10−8 here", True),
        (3, "in 3 dimensions", True),
        (3, "in 3.5 dimensions", False),
    ],
)
def test_get_number_pattern(value, text, found):
    pattern = rv.get_number_pattern(value)
    assert bool(pattern.search(rv.normalize_text(text))) == found


def test_check_value_and_find_number():
    pages = [
        rv.normalize_text("Introduction. We follow prior work closely."),
        rv.normalize_text(
            "Methods. Input positions are perturbed by Gaussian noise with "
            "σ = 0.1 during training, and the learning rate is 10−3."
        ),
    ]
    quote = "perturbed by Gaussian noise with σ = 0.1"
    assert rv.check_value(pages, 0.1, page=2, quote=quote) is None
    # Spacing doesn't count, since text extraction spaces things its own way
    assert rv.check_value(pages, 0.1, page=2, quote="noise with σ=0.1") is None
    assert rv.check_value(pages, 0.1, page=2) is None
    assert rv.check_value(pages, 0.1) is None
    assert rv.check_value(pages, 0.1, page=1, quote=quote) == (
        "the quote is on page 2, not 1"
    )
    assert rv.check_value(pages, 0.2, page=2, quote=quote) == (
        "the quote doesn't contain 0.2"
    )
    assert rv.check_value(pages, 0.1, quote="noise with σ = 0.1 always") == (
        "the quote isn't in the PDF"
    )
    assert rv.check_value(pages, 0.1, page=1) == "0.1 isn't on page 1"
    assert rv.check_value(pages, 0.1, page=3) == "the PDF has 2 pages, not 3"
    assert rv.check_value(pages, "lots") == "'lots' isn't a number"
    (match,) = rv.find_number(pages, 0.1)
    assert match.page == 2
    assert match.text == "0.1"
    assert "Gaussian noise with σ = 0.1 during" in match.quote


def test_read_pdf_pages(tmp_path):
    pdf = write_pdf(
        tmp_path / "liu2025.pdf",
        [
            ["A Title"],
            [
                "Positions are perturbed by Gaussian noise with",
                "sigma = 0.1 during training.",
            ],
        ],
    )
    pages = rv.read_pdf_pages(pdf)
    assert len(pages) == 2
    assert "noise with sigma = 0.1 during" in pages[1]
    (match,) = rv.find_number(pages, "0.10")
    assert match.page == 2


def test_get_pdf(tmp_path, monkeypatch):
    # A file the entry names comes first, then one downloaded before, then
    # Zotero, then a download, which is kept in .calkit/local
    wdir = str(tmp_path)
    write_pdf(tmp_path / "liu.pdf", [["x"]])
    found = rv.get_pdf("refs.bib", "liu2025", file="liu.pdf", wdir=wdir)
    assert found.source == "liu.pdf"
    search = rv.PdfSearch()
    assert rv.get_pdf("refs.bib", "liu2025", wdir=wdir, search=search) is None
    assert search.tried == []
    # Linked to Zotero, Zotero desktop is asked for the attachment, and
    # then the Calkit Cloud
    os.makedirs(tmp_path / ".calkit" / "zotero")
    (tmp_path / rv.ZOTERO_SYNC_INFO_PATH).write_text(
        json.dumps({"refs.bib": {"library_type": "user", "library_id": "9"}})
    )
    (tmp_path / rv.ZOTERO_ITEMS_PATH).write_text(
        json.dumps(
            {
                "refs.bib": {
                    "liu2025": {
                        "item_key": "ITEM",
                        "pdf_attachment_keys": ["ATT1"],
                    }
                }
            }
        )
    )
    asked = []

    def local(link, item):
        asked.append((link["library_type"], item["pdf_attachment_keys"]))
        return tmp_path / "liu.pdf"

    monkeypatch.setattr(rv, "get_zotero_local_pdf", local)
    found = rv.get_pdf("refs.bib", "liu2025", wdir=wdir)
    assert found.source == "Zotero desktop"
    assert asked == [("user", ["ATT1"])]
    monkeypatch.setattr(rv, "get_zotero_local_pdf", lambda link, item: None)
    monkeypatch.setattr(
        rv, "get_cloud_pdf", lambda path, key, dest, wdir=None: None
    )
    search = rv.PdfSearch()
    assert rv.get_pdf("refs.bib", "liu2025", wdir=wdir, search=search) is None
    assert search.tried == ["Zotero desktop", "the Calkit Cloud's Zotero link"]
    # Downloads only when asked, and kept for next time
    entry = {"archiveprefix": "arXiv", "eprint": "2507.06952"}

    def download(url, dest):
        assert url == "https://arxiv.org/pdf/2507.06952"
        write_pdf(dest, [["y"]])
        return dest

    monkeypatch.setattr(rv, "download_pdf", download)
    assert rv.get_pdf("refs.bib", "liu2025", entry=entry, wdir=wdir) is None
    found = rv.get_pdf(
        "refs.bib", "liu2025", entry=entry, wdir=wdir, download=True
    )
    assert found.source == "https://arxiv.org/pdf/2507.06952"
    assert found.path == tmp_path / rv.PDF_CACHE_DIR / "liu2025.pdf"
    monkeypatch.setattr(rv, "download_pdf", None)
    found = rv.get_pdf("refs.bib", "liu2025", entry=entry, wdir=wdir)
    assert found.source == "downloaded"


def test_get_open_access_urls():
    class Lookup:
        def get_json(self, url):
            assert url == "https://api.openalex.org/works/doi:10.1/abc"
            return {
                "best_oa_location": {"pdf_url": "https://x.org/a.pdf"},
                "oa_locations": [
                    {"pdf_url": "https://x.org/a.pdf"},
                    {"pdf_url": None},
                    {"pdf_url": "https://y.org/b.pdf"},
                ],
            }

    assert rv.get_open_access_urls({"doi": "10.1/abc"}, Lookup()) == [
        "https://x.org/a.pdf",
        "https://y.org/b.pdf",
    ]
    assert rv.get_open_access_urls(
        {"doi": "10.48550/arXiv.2507.06952"}, None
    ) == ["https://arxiv.org/pdf/2507.06952"]
    assert rv.get_open_access_urls(
        {"url": "https://arxiv.org/abs/2507.06952v2"}, None
    ) == ["https://arxiv.org/pdf/2507.06952"]
    assert rv.get_open_access_urls({}, None) == []


def test_get_zotero_local_pdf(tmp_path, monkeypatch):
    # The local API answers with the file's URL on disk
    pdf = write_pdf(tmp_path / "a.pdf", [["x"]])
    urls = []

    class Response:
        def __init__(self, text):
            self.text = text

        def read(self):
            return self.text.encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(url, timeout=None):
        urls.append(url)
        if "MISSING" in url:
            raise OSError("not found")
        return Response(pdf.as_uri())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    item = {"pdf_attachment_keys": ["MISSING", "ATT2"]}
    assert rv.get_zotero_local_pdf({"library_type": "user"}, item) == pdf
    assert urls == [
        f"{rv.ZOTERO_LOCAL_URL}/users/0/items/MISSING/file/view/url",
        f"{rv.ZOTERO_LOCAL_URL}/users/0/items/ATT2/file/view/url",
    ]
    urls.clear()
    link = {"library_type": "group", "library_id": "77"}
    assert rv.get_zotero_local_pdf(link, {"pdf_attachment_keys": ["A"]}) == pdf
    assert urls == [f"{rv.ZOTERO_LOCAL_URL}/groups/77/items/A/file/view/url"]


def test_values_file_and_latex_deps(tmp_dir):
    # Values are written to a file of their own when the pipeline compiles,
    # and a LaTeX stage quoting one depends on it, not on calkit.yaml
    import subprocess

    import calkit
    import calkit.latex
    import calkit.pipeline

    subprocess.check_call(["calkit", "init"], stdout=subprocess.DEVNULL)
    os.makedirs("paper")
    with open("paper/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n\\usepackage{calkit}\n"
            "\\begin{document}\n"
            "Noise \\ckrefval[.2f]{liu.2025}{noise-sigma} \\cite{liu.2025}.\n"
            "\\end{document}\n"
        )
    loads, components = calkit.latex.read_ck_usage("paper/main.tex")
    assert loads
    assert components == [
        calkit.latex.CkComponent(
            "value",
            rv.VALUES_PATH,
            "liu.2025.noise-sigma",
            ".2f",
            ref=("liu.2025", "noise-sigma"),
        )
    ]
    ck_info = calkit.load_calkit_info()
    ck_info["references"] = [
        {
            "path": "refs.bib",
            "values": {"liu.2025": {"noise-sigma": {"value": 0.1}}},
        }
    ]
    ck_info["environments"] = {"tex": {"kind": "texlive"}}
    ck_info["pipeline"] = {
        "stages": {
            "paper": {
                "kind": "latex",
                "target_path": "paper/main.tex",
                "environment": "tex",
            }
        }
    }
    calkit.save_calkit_info(ck_info)
    stages = calkit.pipeline.to_dvc(write=True)
    with open(rv.VALUES_PATH) as f:
        assert json.load(f) == {"liu.2025": {"noise-sigma": 0.1}}
    assert rv.VALUES_PATH in stages["paper"]["deps"]
    assert "calkit.yaml" not in stages["paper"]["deps"]
    # A citation key with dots is found by the dotted lookup
    calkit.latex.map_ck_components("paper/main.tex")
    with open("paper/_calkit/values.tex") as f:
        assert (
            f"\\cksetvalue{{{rv.VALUES_PATH}}}{{liu.2025.noise-sigma}}{{n}}"
            "{0.1}"
        ) in f.read()
    # With none declared, the file goes away
    ck_info["references"] = [{"path": "refs.bib"}]
    calkit.save_calkit_info(ck_info)
    calkit.pipeline.to_dvc(write=True)
    assert not os.path.exists(rv.VALUES_PATH)


def _make_project(with_wrong_page: bool = True) -> None:
    """A project with a Quarto document quoting values from a reference
    whose PDF the collection names.
    """
    import subprocess

    import calkit

    subprocess.check_call(["calkit", "init"], stdout=subprocess.DEVNULL)
    write_pdf(
        Path("refs/liu2025.pdf"),
        [
            ["Title page"],
            [
                "Positions are perturbed by Gaussian noise with",
                "sigma = 0.1 during training, at a learning rate of 0.001.",
            ],
        ],
    )
    Path("refs.bib").write_text(
        "@article{liu2025, title={Orbits}, author={Liu, A.}}\n"
        "@article{wu2024, title={Other}, author={Wu, B.}}\n"
    )
    Path("index.qmd").write_text(
        "---\ntitle: Test\nbibliography: refs.bib\n---\n\n"
        "We perturb inputs with noise of 0.10, as in [@liu2025].\n\n"
        "The rate is {{< ckrefval liu2025 lr >}} [@liu2025], and the batch "
        "is {{< ckrefval liu2025 batch >}}.\n\n"
        "Wu reports {{< ckrefval wu2024 speed >}}, and 0.77 [@liu2025].\n"
    )
    ck_info = calkit.load_calkit_info()
    ck_info["references"] = [
        {
            "path": "refs.bib",
            "files": {"liu2025": "refs/liu2025.pdf"},
            "values": {
                "liu2025": {
                    "lr": {
                        "value": 0.001,
                        "page": 1 if with_wrong_page else 2,
                        "quote": "at a learning rate of 0.001",
                    }
                },
                "wu2024": {"speed": {"value": 3.5}},
            },
        }
    ]
    ck_info["environments"] = {"py": {"kind": "uv", "path": "pyproject.toml"}}
    ck_info["pipeline"] = {
        "stages": {
            "pub": {
                "kind": "quarto",
                "target_path": "index.qmd",
                "environment": "py",
            }
        }
    }
    calkit.save_calkit_info(ck_info)


def test_check_reproducibility_refvals(tmp_dir):
    from calkit.reproducibility import check_reproducibility

    _make_project()
    res = check_reproducibility(log_func=lambda *a: None, offline=True)
    assert res.n_refvals == 2
    assert [
        (p["file"], p["line"], p["key"], p["name"], p["problem"])
        for p in res.refval_problems
    ] == [
        (
            "calkit.yaml",
            0,
            "liu2025",
            "lr",
            "in refs/liu2025.pdf, the quote is on page 2, not 1",
        ),
        (
            "index.qmd",
            8,
            "liu2025",
            "batch",
            "calkit.yaml records no value 'batch' quoted from 'liu2025'",
        ),
        (
            "index.qmd",
            10,
            "wu2024",
            "speed",
            "it quotes wu2024 but never cites it",
        ),
    ]
    assert [(u["key"], u["name"]) for u in res.refvals_unchecked] == [
        ("wu2024", "speed")
    ]
    # A typed number in a sentence citing the reference is looked for in
    # its PDF: one is found, and one isn't there
    by_value = {f["value"]: f for f in res.unattributed_numbers}
    (found,) = by_value["0.10"]["found"]
    assert (found["key"], found["page"], found["source"]) == (
        "liu2025",
        2,
        "refs/liu2025.pdf",
    )
    assert "noise with sigma = 0.1 during" in found["quote"]
    assert by_value["0.77"]["searched"] == ["liu2025"]
    assert "Problems with values quoted from references: 3" in res.to_pretty()


def test_check_repro_refvals_cli(tmp_dir):
    import subprocess

    _make_project()
    env = os.environ | {"COLUMNS": "200"}
    out = subprocess.check_output(
        ["calkit", "check", "repro", "--offline", "-c", "numbers"],
        text=True,
        env=env,
    )
    # Brackets come through, rather than reading as Rich's markup
    assert "as in [@liu2025]" in out
    assert "p. 2 of liu2025" in out
    assert "not in liu2025" in out
    assert "calkit new ref-value liu2025 <name> --value 0.10 --page 2" in out
    out = subprocess.check_output(
        ["calkit", "check", "repro", "--offline", "-c", "refvals"],
        text=True,
        env=env,
    )
    assert "the quote is on page 2, not 1" in out
    # Recording one checks it against the PDF first
    p = subprocess.run(
        [
            "calkit",
            "new",
            "ref-value",
            "liu2025",
            "noise",
            "--value",
            "0.2",
            "--page",
            "2",
            "--quote",
            "Gaussian noise with sigma = 0.1",
        ],
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "the quote doesn't contain 0.2" in p.stderr
    subprocess.check_call(
        [
            "calkit",
            "new",
            "ref-value",
            "liu2025",
            "noise",
            "--value",
            "0.1",
            "--page",
            "2",
            "--quote",
            "Gaussian noise with sigma = 0.1",
        ],
        stdout=subprocess.DEVNULL,
    )
    import calkit

    values = calkit.load_calkit_info()["references"][0]["values"]["liu2025"]
    assert values["noise"] == {
        "value": 0.1,
        "page": 2,
        "quote": "Gaussian noise with sigma = 0.1",
    }
    p = subprocess.run(
        ["calkit", "new", "ref-value", "nobody", "x", "--value", "1"],
        capture_output=True,
        text=True,
    )
    assert "No reference collection defines 'nobody'" in p.stderr


def test_check_project_bibliographies(tmp_dir):
    # A key is checked against the bibliographies the citing document names
    import calkit

    _make_project(with_wrong_page=False)
    Path("other.bib").write_text(
        "@article{liu2025, title={Something else}, author={Liu, A.}}\n"
        "@article{dup, title={A}}\n@article{dup, title={B}}\n"
    )
    Path("index.qmd").write_text(
        "---\nbibliography: [refs.bib, other.bib]\n---\n\n"
        "Rate {{< ckrefval liu2025 lr >}} [@liu2025].\n"
    )
    ck_info = calkit.load_calkit_info()
    ck_info["references"].append({"path": "other.bib"})
    found = rv.check_project(ck_info, ["index.qmd"], download=False)[
        "problems"
    ]
    assert [p["problem"] for p in found] == [
        "dup is defined 2 times",
        "liu2025 is a different entry in refs.bib and other.bib",
    ]


def test_reference_files():
    # Files are by citation key, and the list of key and path Calkit wrote
    # before still reads
    from calkit.models.core import ReferenceCollection

    old = {"path": "r.bib", "files": [{"key": "a", "path": "a.pdf"}]}
    new = {"path": "r.bib", "files": {"a": "a.pdf"}}
    assert rv.get_reference_files(old) == {"a": "a.pdf"}
    assert rv.get_reference_files(new) == {"a": "a.pdf"}
    assert (
        rv.get_entry_file(old, "a") == rv.get_entry_file(new, "a") == "a.pdf"
    )
    assert rv.get_entry_file(new, "b") is None
    assert rv.get_reference_files({"path": "r.bib"}) == {}
    assert ReferenceCollection.model_validate(old).files == {"a": "a.pdf"}
    assert ReferenceCollection.model_validate(new).files == {"a": "a.pdf"}
