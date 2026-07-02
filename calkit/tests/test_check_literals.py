"""Unit tests for checking literals."""

import pytest

from calkit.check_literals import find_untraceable_literals


def extract_values(tex_source, from_json_values=None):
    findings = find_untraceable_literals(
        tex_source, "main.tex", from_json_values
    )
    return [f["value"] for f in findings]


@pytest.mark.parametrize(
    "tex_source, expected_values",
    [
        # Flag cases
        ("Here is a hardcoded decimal: 3.14.", ["3.14"]),
        ("And another one in math mode: $0.42$.", ["0.42"]),
        (r"Uncertainty $0.42 \pm 0.03$ is flagged.", [r"0.42 \pm 0.03"]),
        ("Scientific $1.2e-3$ is flagged.", ["1.2e-3"]),
        (r"But this 12.7\% is flagged.", [r"12.7\%"]),
    ],
    ids=[
        "decimal_in_prose",
        "decimal_in_math",
        "uncertainty",
        "scientific",
        "percent",
    ],
)
def test_find_untraceable_literals_flags(tex_source, expected_values):
    assert extract_values(tex_source) == expected_values


@pytest.mark.parametrize(
    "tex_source",
    [
        r"reported \resultCd in the text",
        r"\cite{smith2020}",
        r"\href{https://example.com}{the value 1.2}",
        r"\url{http://9.8.7.6/data}",
        "10.1017/jfm.2020.123",
        "2023",
        r"pp.\ 123--145",
        "we ran 12 simulations",
        "% ... 9.81 ...",
        r"\begin{thebibliography} 4.56 \end{thebibliography}",
        r"\includegraphics[width=0.8\textwidth]{fig.pdf}",
        r"\setlength{\parindent}{0.5in}",
        r"\geometry{margin=1.5cm}",
        r"See Fig.~\ref{fig:1} and Eq.~\eqref{eq:2}",
    ],
    ids=[
        "macro",
        "cite",
        "href",
        "url",
        "bare_doi",
        "year",
        "page_range",
        "integer_count",
        "latex_comment",
        "bibliography_body",
        "includegraphics",
        "setlength",
        "geometry",
        "ref_eqref",
    ],
)
def test_find_untraceable_literals_excludes(tex_source):
    assert extract_values(tex_source) == []


def test_find_untraceable_literals_traceable():
    assert extract_values("... 1.23 ...", {"1.23": "trackedVal"}) == []


def test_find_untraceable_literals_shape():
    findings = find_untraceable_literals("3.14", "main.tex")
    assert len(findings) == 1
    finding = findings[0]
    assert "value" in finding
    assert finding["value"] == "3.14"
    assert "suggestion" in finding
    assert finding["suggestion"] != ""
    assert "file" in finding
    assert finding["file"] == "main.tex"
    assert "line" in finding
    assert "column" in finding
    assert "reason" in finding
