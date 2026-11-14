"""Tests for ``calkit.environments.texlive``."""

import io
import json
import os
import subprocess
import sys
import tarfile
import time

import pytest

import calkit
from calkit.environments import texlive

TLPDB = """name 00texlive.config
category TLCore
revision 1
depend frozen/1
depend release/2025

name latex-bin
category TLCore
revision 10
depend latex
depend latex-bin.ARCH
depend opt_foo:1
execute AddFormat name=pdflatex engine=pdftex options="*pdflatex.ini"
containersize 600
containerchecksum aaa
runfiles size=1
 texmf-dist/tex/latex/latex-bin/x.cfg

name latex-bin.universal-darwin
category TLCore
revision 11
containersize 300
containerchecksum bbb
binfiles arch=universal-darwin size=1
 bin/universal-darwin/pdflatex

name latex-bin.windows
category TLCore
revision 12
containersize 300
containerchecksum ccc
binfiles arch=windows size=1
 bin/windows/pdflatex.exe

name latex
category Package
revision 20
containersize 1000
containerchecksum ddd
docfiles size=1
 texmf-dist/doc/latex/base/README.md
runfiles size=2
 texmf-dist/tex/latex/base/article.cls
 texmf-dist/tex/latex/base/size10.clo

name latex-tools-dev
category Package
revision 30
containersize 10
containerchecksum eee
runfiles size=1
 texmf-dist/tex/latex-dev/tools/array.sty

name tools
category Package
revision 31
containersize 10
containerchecksum fff
runfiles size=1
 texmf-dist/tex/latex/tools/array.sty
"""


def test_parse_and_resolve(tmp_path, monkeypatch):
    tlpdb = texlive.parse_tlpdb(TLPDB)
    assert tlpdb["latex-bin"]["revision"] == 10
    assert tlpdb["latex-bin"]["executes"] == [
        'AddFormat name=pdflatex engine=pdftex options="*pdflatex.ini"'
    ]
    # Documentation isn't kept, only what a build reads
    assert tlpdb["latex"]["runfiles"] == [
        "texmf-dist/tex/latex/base/article.cls",
        "texmf-dist/tex/latex/base/size10.clo",
    ]
    assert texlive.get_tlpdb_release(tlpdb) == 2025
    # Binaries come for each platform locked, and only those, and options
    # and virtual packages without containers aren't packages
    assert texlive.resolve_packages(
        tlpdb, ["latex-bin"], ["universal-darwin", "x86_64-linux"]
    ) == ["latex", "latex-bin", "latex-bin.universal-darwin"]
    assert texlive.resolve_packages(tlpdb, ["latex-bin"], ["windows"]) == [
        "latex",
        "latex-bin",
        "latex-bin.windows",
    ]
    with pytest.raises(ValueError, match="Unknown TeX Live package"):
        texlive.resolve_packages(tlpdb, ["nope"], ["windows"])
    # A package with a dot in its name isn't mistaken for a platform's
    assert texlive.get_package_platform("texlive.infra") is None
    assert texlive.get_package_platform("tlperl.windows") == "windows"
    # The spec hash changes with what the lock is resolved from, not with
    # how the spec is written
    a = texlive.calc_spec_md5({"kind": "texlive", "packages": ["b", "a"]})
    b = texlive.calc_spec_md5({"kind": "texlive", "packages": ["a", "b"]})
    c = texlive.calc_spec_md5({"kind": "texlive", "packages": ["a"]})
    assert a == b != c
    # Locks are only for the platform packages that belong to a platform
    lock = {
        "packages": {
            "latex": {"revision": 20},
            "latex-bin.windows": {"revision": 12},
            "latex-bin.universal-darwin": {"revision": 11},
        }
    }
    assert sorted(texlive.get_platform_packages(lock, "windows")) == [
        "latex",
        "latex-bin.windows",
    ]
    # Two locks with the same packages for a platform share an environment
    assert texlive.calc_view_hash(lock, "windows") == texlive.calc_view_hash(
        {"packages": {**lock["packages"], "x.universal-darwin": {}}},
        "windows",
    )
    # A missing file is found in the database the lock came from, and a
    # release's copy wins over the development format's
    monkeypatch.setattr(
        texlive, "load_tlpdb", lambda repository, max_age_s=0: tlpdb
    )
    assert texlive.find_packages_for_files(
        {"repository": "x"}, ["array.sty", "article.cls", "nope.sty"]
    ) == {"array.sty": "tools", "article.cls": "latex"}
    # Packages a build adds go in the lock, not the spec, and relocking
    # keeps them, unless the spec has them or the release doesn't
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(texlive, "BASE_PACKAGES", ["latex-bin"])
    monkeypatch.setattr(texlive, "get_repository_url", lambda env: "x")
    env = {"kind": "texlive", "platforms": ["windows"]}
    calkit.save_calkit_info({"environments": {"tex": env}})
    lock_fpath = texlive.get_lock_fpath("tex", env)
    texlive.write_lock(texlive.create_lock(env), lock_fpath)
    assert texlive.add_packages("tex", env, ["tools", "latex"]) == ["tools"]
    assert texlive.add_packages("tex", env, ["tools"]) == []
    lock = texlive.read_lock(lock_fpath)
    assert lock is not None
    assert lock["added"] == ["tools"]
    assert sorted(lock["packages"]) == [
        "latex",
        "latex-bin",
        "latex-bin.windows",
        "tools",
    ]
    assert calkit.load_calkit_info()["environments"]["tex"] == env
    relocked = texlive.create_lock(
        {**env, "packages": ["latex-tools-dev"]},
        added=lock["added"] + ["latex-tools-dev", "gone"],
    )
    assert relocked["added"] == ["tools"]
    assert {"tools", "latex-tools-dev"} <= set(relocked["packages"])
    # A switch is resolved to the TeX Live environment it picks here
    calkit.save_calkit_info(
        {
            "environments": {
                "tex": env,
                "py": {"kind": "uv", "path": "pyproject.toml"},
                "any": {"kind": "switch", "switch": [{"use": "tex"}]},
                "inline": {"kind": "switch", "switch": [{"use": env}]},
            }
        }
    )
    assert texlive.get_selected_env("tex") == ("tex", env)
    assert texlive.get_selected_env("any") == ("tex", env)
    assert texlive.get_selected_env("inline") == ("inline.1", env)
    assert texlive.get_selected_env("py") is None
    assert texlive.get_selected_env("nope") is None
    assert texlive.get_selected_env(None) is None


def test_extract_container(tmp_path):
    def make_container(path, members):
        with tarfile.open(path, "w:xz") as tf:
            for name, content in members.items():
                info = tarfile.TarInfo(name)
                if isinstance(content, tuple):
                    info.type = tarfile.SYMTYPE
                    info.linkname = content[0]
                    tf.addfile(info)
                    continue
                data = content.encode()
                info.size = len(data)
                info.mode = 0o755 if name.startswith("bin/") else 0o644
                tf.addfile(info, io.BytesIO(data))

    # A relocatable package's files go under texmf-dist, with a database
    make_container(
        tmp_path / "amsmath.tar.xz",
        {
            "tex/latex/amsmath/amsmath.sty": "% amsmath",
            "tlpkg/tlpobj/amsmath.tlpobj": "name amsmath\nrelocated 1\n",
        },
    )
    dest = tmp_path / "amsmath"
    dest.mkdir()
    texlive.extract_container(str(tmp_path / "amsmath.tar.xz"), str(dest))
    assert (dest / "texmf-dist/tex/latex/amsmath/amsmath.sty").is_file()
    assert (dest / "tlpkg/tlpobj/amsmath.tlpobj").is_file()
    with open(dest / "texmf-dist/ls-R") as f:
        ls_r = f.read()
    assert ls_r.startswith("% ls-R -- filename database for kpathsea")
    assert "./tex/latex/amsmath:\namsmath.sty\n" in ls_r
    # A platform package keeps its layout, and its links into other packages
    members: dict = {"bin/universal-darwin/pdftex": "binary"}
    if sys.platform != "win32":
        members["bin/universal-darwin/pdflatex"] = ("pdftex",)
    make_container(tmp_path / "pdftex.tar.xz", members)
    dest = tmp_path / "pdftex"
    dest.mkdir()
    texlive.extract_container(str(tmp_path / "pdftex.tar.xz"), str(dest))
    assert (dest / "bin/universal-darwin/pdftex").is_file()
    if sys.platform != "win32":
        assert os.access(dest / "bin/universal-darwin/pdftex", os.X_OK)
        assert os.readlink(dest / "bin/universal-darwin/pdflatex") == "pdftex"
    # Nothing is written outside the destination
    make_container(tmp_path / "evil.tar.xz", {"../evil.sty": "x"})
    dest = tmp_path / "evil"
    dest.mkdir()
    with pytest.raises(ValueError, match="Unsafe path"):
        texlive.extract_container(str(tmp_path / "evil.tar.xz"), str(dest))
    assert not (tmp_path / "evil.sty").exists()


def test_create_language_files_and_font_maps(tmp_path):
    def make_pkg(name, executes, files):
        pkg_dir = tmp_path / "pkgs" / name
        (pkg_dir / "tlpkg" / "tlpobj").mkdir(parents=True)
        with open(pkg_dir / "tlpkg" / "tlpobj" / f"{name}.tlpobj", "w") as f:
            f.write(f"name {name}\n")
            f.writelines(f"execute {e}\n" for e in executes)
        for rel, content in files.items():
            path = pkg_dir / "texmf-dist" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return str(pkg_dir)

    config = "tex/generic/config/"
    pkg_dirs = {
        "hyphen-base": make_pkg(
            "hyphen-base",
            [],
            {
                config + "language.us": "english hyphen.tex\n",
                config + "language.us.def": "%% language.def\n",
                config + "language.us.lua": "return {\n",
            },
        ),
        "hyphen-german": make_pkg(
            "hyphen-german",
            [
                "AddHyphen name=german synonyms=deutsch lefthyphenmin=2 "
                "righthyphenmin=2 file=loadhyph-de.tex "
                "file_patterns=hyph-de.pat.txt file_exceptions=",
                "AddHyphen name=ngerman databases=dat lefthyphenmin=2 "
                "righthyphenmin=2 file=dehyphn.tex",
            ],
            {},
        ),
        "cm": make_pkg(
            "cm",
            ["addMap cm.map"],
            {
                "fonts/map/dvips/cm/cm.map": "% comment\n"
                "cmr10 CMR10 <cmr10.pfb\ncmbx10 CMBX10 <cmbx10.pfb\n"
            },
        ),
        "ams": make_pkg(
            "ams",
            ["addMixedMap ams.map"],
            {
                "fonts/map/dvips/ams/ams.map": "cmr10 Other <other.pfb\n"
                "msam10 MSAM10 <msam10.pfb\n"
            },
        ),
    }
    out = tmp_path / "var"
    contents = texlive.create_language_files(pkg_dirs, str(out))
    dat = (out / config / "language.dat").read_text()
    assert dat == contents["language.dat"]
    assert "english hyphen.tex\n% from hyphen-german:\n" in dat
    assert "german loadhyph-de.tex\n=deutsch\nngerman dehyphn.tex\n" in dat
    # Each database only gets the languages that say they belong in it, and
    # language.def keeps its identifying first line
    dfn = contents["language.def"]
    assert dfn.startswith("%% language.def\n")
    assert "\\addlanguage{deutsch}{loadhyph-de.tex}{}{2}{2}" in dfn
    assert "ngerman" not in dfn
    assert dfn.rstrip().endswith("last line of the file.")
    lua = contents["language.dat.lua"]
    assert "\t['german'] = {\n" in lua
    assert "\t\tpatterns = 'hyph-de.pat.txt',\n" in lua
    assert "hyphenation" not in lua
    assert lua.endswith("}\n")
    texlive.create_font_maps(pkg_dirs, str(out))
    pdftex_map = (out / "fonts/map/pdftex/updmap/pdftex.map").read_text()
    # Packages are read in order of name, and the first entry for a font
    # wins, with comments left out
    assert pdftex_map.splitlines()[1:] == [
        "cmr10 Other <other.pfb",
        "msam10 MSAM10 <msam10.pfb",
        "cmbx10 CMBX10 <cmbx10.pfb",
    ]
    assert (out / "fonts/map/dvips/updmap/psfonts.map").is_file()


@pytest.mark.xdist_group("texlive")
def test_check_and_run(tmp_dir, texlive_user_home, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", texlive_user_home)
    env: dict = {"kind": "texlive"}
    calkit.save_calkit_info({"environments": {"tex": env}})
    # Locking resolves the base packages for every platform, and checking
    # installs this platform's and assembles them
    view_dir = texlive.check("tex", env)
    lock_fpath = os.path.join(".calkit", "env-locks", "tex.json")
    lock = texlive.read_lock(lock_fpath)
    assert lock is not None
    assert lock["release"] == texlive.DEFAULT_RELEASE
    assert lock["platforms"] == texlive.DEFAULT_LOCK_PLATFORMS
    for name in texlive.BASE_PACKAGES:
        assert name in lock["packages"]
    assert "pdftex.windows" in lock["packages"]
    assert "pdftex.x86_64-linux" in lock["packages"]
    platform = texlive.get_platform()
    assert view_dir == texlive.get_view_dir(lock, platform)
    # Its programs find its own configuration, with nothing from elsewhere
    # on the machine, e.g., a user's own texmf tree
    exe = ".exe" if platform == "windows" else ""
    out = subprocess.run(
        [
            os.path.join(view_dir, "bin", platform, "kpsewhich" + exe),
            "-var-value",
            "TEXMFHOME",
        ],
        env=texlive.get_run_env_vars(view_dir),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out.replace("\\", "/").startswith(view_dir.replace("\\", "/"))
    # Checking a ready environment reads its lock and nothing else
    started = time.perf_counter()
    for _ in range(10):
        texlive.check("tex", env)
    assert (time.perf_counter() - started) / 10 < 0.05
    with open(lock_fpath) as f:
        assert json.load(f) == lock
    # Documents compile with pdfLaTeX and LuaLaTeX
    with open("doc.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n\\usepackage{graphicx}\n"
            "\\begin{document}\nHello, $x^2$.\n\\end{document}\n"
        )
    for engine in ["-pdf", "-lualatex"]:
        assert not texlive.run(view_dir, ["latexmk", "-C"])
        status = texlive.run(
            view_dir,
            ["latexmk", engine, "-interaction=nonstopmode", "doc.tex"],
        )
        assert status == 0, engine
        assert os.path.isfile("doc.pdf")
    # A document naming a package the environment lacks gets it added to
    # the lock, and the environment assembled again reuses the store
    with open("doc2.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n\\usepackage{booktabs}\n"
            "\\begin{document}\n\\begin{tabular}{l}\\toprule a\\\\\n"
            "\\bottomrule\\end{tabular}\n\\end{document}\n"
        )
    formats_dir = os.path.join(texlive.get_store_dir(), "formats")
    formats_before = sorted(os.listdir(formats_dir))
    added = texlive.add_document_packages("tex", env, "doc2.tex")
    assert added == {"booktabs.sty": "booktabs"}
    assert texlive.add_document_packages("tex", env, "doc2.tex") == {}
    assert texlive.add_packages("tex", env, ["booktabs", "latex-bin"]) == []
    assert "packages" not in calkit.load_calkit_info()["environments"]["tex"]
    lock = texlive.read_lock(lock_fpath)
    assert lock is not None
    assert lock["added"] == ["booktabs"]
    new_view_dir = texlive.check("tex", env)
    assert new_view_dir != view_dir
    assert os.path.isdir(view_dir)
    assert sorted(os.listdir(formats_dir)) == formats_before
    assert not texlive.run(
        new_view_dir, ["pdflatex", "-interaction=nonstopmode", "doc2.tex"]
    )
    # Rebuilding assembles the environment again from the store
    assert texlive.check("tex", env, rebuild=True) == new_view_dir
