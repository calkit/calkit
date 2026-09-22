"""Find the TeX Live packages recent arXiv papers load that the image lacks.

Samples recent submissions across a spread of categories, reads each
source's \\usepackage, \\RequirePackage, and \\documentclass lines, and
checks every name against an image with kpsewhich. What's missing is mapped
to the TeX Live package that provides it, from the TeX Live package
database, and printed ranked by how many papers load it.

Usage:

    python scan-arxiv.py --image ghcr.io/calkit/latex:0.1.2
    python scan-arxiv.py --image calkit/latex:dev --write packages.txt

Requests are spaced 3 s apart, as arXiv asks of automated access, so a
full scan of the default sample takes about ten minutes. Only direct loads
are seen: what a package loads in turn surfaces when compiling, not here.
"""

import argparse
import collections
import gzip
import io
import json
import lzma
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time

CATEGORIES = [
    "cs.LG",
    "cs.CV",
    "cs.CL",
    "cs.RO",
    "math.AP",
    "math.PR",
    "stat.ME",
    "physics.flu-dyn",
    "cond-mat.mtrl-sci",
    "astro-ph.GA",
    "hep-ph",
    "quant-ph",
    "eess.SY",
    "q-bio.NC",
    "econ.EM",
    "physics.ao-ph",
]
TLPDB_URL = (
    "https://mirror.ctan.org/systems/texlive/tlnet/tlpkg/texlive.tlpdb.xz"
)
USER_AGENT = "calkit-latex-image-scan (https://github.com/calkit/calkit)"
PKG_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}"
)
CLS_RE = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
COMMENT_RE = re.compile(r"(?<!\\)%.*")


def get(url: str) -> bytes:
    # arXiv answers Python's urllib with 406, so fetch the way a browser
    # or curl would
    return subprocess.run(
        ["curl", "-sfL", "--max-time", "90", "-A", USER_AGENT, url],
        check=True,
        capture_output=True,
    ).stdout


def read_eprint(blob: bytes) -> tuple[list[str], set[str]]:
    """The TeX sources in an e-print, and the style names it ships."""
    texts, local = [], set()
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                stem, _, ext = member.name.rpartition(".")
                if ext in ("sty", "cls"):
                    # Loaded by path or by bare name, depending on the paper
                    local.add(stem)
                    local.add(stem.rsplit("/", 1)[-1])
                if ext in ("tex", "sty", "cls", "ltx"):
                    f = tar.extractfile(member)
                    if f is not None:
                        texts.append(f.read().decode("latin1"))
        return texts, local
    except tarfile.TarError:
        pass
    try:
        data = gzip.decompress(blob)
    except OSError:
        data = blob
    if data[:4] == b"%PDF":
        return [], set()
    return [data.decode("latin1")], set()


def scan(per_category: int) -> list[dict]:
    """What each sampled paper loads that it doesn't ship itself."""
    ids = []
    for cat in CATEGORIES:
        feed = get(
            "https://export.arxiv.org/api/query?search_query=cat:"
            f"{cat}&sortBy=submittedDate&sortOrder=descending"
            f"&max_results={per_category}"
        ).decode()
        found = re.findall(
            r"<id>http://arxiv.org/abs/([^<]+?)(?:v\d+)?</id>", feed
        )
        ids += [i for i in found if i not in ids]
        time.sleep(3)
    papers = []
    for arxiv_id in ids:
        time.sleep(3)
        try:
            texts, local = read_eprint(
                get(f"https://arxiv.org/e-print/{arxiv_id}")
            )
        except subprocess.CalledProcessError as e:
            print(f"Skipping {arxiv_id}: {e}", file=sys.stderr)
            continue
        if not texts:
            continue
        loads = set()
        for text in texts:
            text = COMMENT_RE.sub("", text)
            for names in PKG_RE.findall(text):
                loads |= {f"{n.strip()}.sty" for n in names.split(",")}
            for name in CLS_RE.findall(text):
                loads.add(f"{name.strip()}.cls")
        papers.append(
            {
                "id": arxiv_id,
                "loads": sorted(
                    f
                    for f in loads
                    if f[:-4] not in local and f not in (".sty", ".cls")
                ),
            }
        )
        print(f"Scanned {len(papers)} ({arxiv_id})", file=sys.stderr)
    return papers


def missing_from(image: str, files: set[str]) -> set[str]:
    """Which of the files kpsewhich can't find in the image."""
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "files.txt"), "w") as f:
            f.write("\n".join(sorted(files)) + "\n")
        out = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{tmp}:/scan",
                image,
                "sh",
                "-c",
                'while read -r f; do kpsewhich "$f" >/dev/null '
                '|| echo "$f"; done < /scan/files.txt',
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    return set(out.split())


def texlive_owners() -> tuple[dict[str, str], dict[str, int]]:
    """Which TeX Live package provides each .sty and .cls, and their sizes."""
    tlpdb = lzma.decompress(get(TLPDB_URL)).decode("utf-8", "replace")
    owner: dict[str, str] = {}
    size: dict[str, int] = {}
    pkg = None
    in_runfiles = False
    for line in tlpdb.splitlines():
        if line.startswith("name "):
            pkg = line.split()[1]
            in_runfiles = False
        elif line.startswith("runfiles") and pkg is not None:
            in_runfiles = True
            m = re.search(r"size=(\d+)", line)
            # Sizes are given in 4 KiB blocks
            size[pkg] = int(m.group(1)) * 4096 if m else 0
        elif not line.startswith(" "):
            in_runfiles = False
        elif in_runfiles and pkg is not None and "." not in pkg:
            base = line.split()[0].rsplit("/", 1)[-1]
            if base.endswith((".sty", ".cls")):
                owner.setdefault(base, pkg)
    return owner, size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", required=True, help="Image to check.")
    parser.add_argument(
        "--per-category",
        type=int,
        default=12,
        help="Recent papers to sample from each category.",
    )
    parser.add_argument(
        "--papers",
        help="Scan results from an earlier run to reuse instead of "
        "scanning, as written by --save-papers.",
    )
    parser.add_argument("--save-papers", help="Where to save scan results.")
    parser.add_argument(
        "--write",
        help="Package list to add the missing packages to, e.g., "
        "packages.txt, keeping what's there.",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Packages to leave out, e.g., large fonts one paper uses.",
    )
    args = parser.parse_args()
    if args.papers:
        with open(args.papers) as f:
            papers = json.load(f)
    else:
        papers = scan(args.per_category)
    if args.save_papers:
        with open(args.save_papers, "w") as f:
            json.dump(papers, f, indent=1)
    missing = missing_from(args.image, {f for p in papers for f in p["loads"]})
    owner, size = texlive_owners()
    uses: collections.Counter[str] = collections.Counter()
    unavailable: collections.Counter[str] = collections.Counter()
    covered = 0
    for paper in papers:
        needs = {f for f in paper["loads"] if f in missing}
        covered += not needs
        for pkg in {owner[f] for f in needs if f in owner}:
            uses[pkg] += 1
        for f in needs - owner.keys():
            unavailable[f] += 1
    n = len(papers)
    print(f"{covered}/{n} papers load nothing missing from {args.image}")
    for pkg, count in uses.most_common():
        print(f"{count:4d}  {size.get(pkg, 0) / 1e6:6.1f} MB  {pkg}")
    if unavailable:
        print("Not in TeX Live:", ", ".join(sorted(unavailable)))
    if args.write:
        existing = set()
        if os.path.isfile(args.write):
            with open(args.write) as f:
                existing = {
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                }
        chosen = existing | (set(uses) - set(args.exclude))
        with open(args.write, "w") as f:
            f.write("\n".join(sorted(chosen)) + "\n")
        print(f"Wrote {len(chosen)} packages to {args.write}")


if __name__ == "__main__":
    main()
