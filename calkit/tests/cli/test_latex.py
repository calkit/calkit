"""Tests for ``calkit.cli.latex.``"""

import json
import os
import subprocess

from pypdf import PdfReader


def test_from_json(tmp_dir):
    os.makedirs("paper")
    tex_doc_content = r"""
\documentclass[11pt]{article}
\input{results.tex}
\begin{document}
This is the document.
The result is \theresults[result1].
The other result is \theresults[lol].
Another is \theresults[sup].
\end{document}
"""
    with open("paper/main.tex", "w") as f:
        f.write(tex_doc_content)
    data = {"sup": 5.555, "lol": 3}
    with open("test.json", "w") as f:
        json.dump(data, f)
    fmt_dict = {
        "result1": "{sup / lol * 1e5 + 22:.1f}",
        "result2": "sup is {sup} and lol is {lol}",
        "result3": "{sup * 1e12:.1e}",
        "lol": "{lol}",
    }
    subprocess.run(
        [
            "calkit",
            "latex",
            "from-json",
            "test.json",
            "-o",
            "paper/results.tex",
            "--command",
            "theresults",
            "--format-json",
            json.dumps(fmt_dict),
        ],
        check=True,
    )
    subprocess.run(["calkit", "latex", "build", "paper/main.tex"], check=True)
    # Read the generated PDF and check that the values are correct
    reader = PdfReader("paper/main.pdf")
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    assert "This is the document." in text
    assert "The result is 185188.7." in text
    assert "The other result is 3." in text
    assert "Another is 5.555." in text
    # Now test some input validation
    with open("bad.json", "w") as f:
        f.write("not valid json")
    out = subprocess.run(
        [
            "calkit",
            "latex",
            "from-json",
            "bad.json",
            "--output",
            "paper/results.tex",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert out.returncode != 0
    assert "not valid JSON" in out.stderr
    # Test that we can supply multiple input files
    with open("test2.json", "w") as f:
        json.dump({"result4": "hello"}, f)
    subprocess.run(
        [
            "calkit",
            "latex",
            "from-json",
            "test.json",
            "test2.json",
            "-o",
            "paper/results.tex",
            "--format-json",
            json.dumps(fmt_dict),
        ],
        check=True,
    )


def test_build(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("paper", exist_ok=True)
    with open("paper/main.tex", "w") as f:
        f.write(
            r"""\documentclass{article}
            \begin{document}
            Hello, world!
            \end{document}
            """
        )
    subprocess.check_call(["calkit", "latex", "build", "paper/main.tex"])
    assert os.path.isfile("paper/main.pdf")
