"""The report's numbers: which result each one reports, and reading them.

Every arm's report has the same Methods and eight numbered results, so the
numbers are found by the phrases around them, not by position, which
tolerates an agent rewording a line or adding results.
"""

import math
import re

NUM = r"[-−]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
CI = rf"CI[^0-9−-]*?({NUM})\s*(?:to|,|–|—|-(?=\d))\s*({NUM})"
P = rf"\bp\s*(<|=|≤|<=)\s*({NUM})"
# Phrase identifying each numbered result's line
ITEMS = {
    1: r"analysis sample",
    2: r"[Mm]ean baseline score",
    3: r"[Mm]ean week.12 score",
    4: r"training raised week.12 scores",
    5: r"change.score sensitivity",
    6: r"graduate education",
    7: r"years of age",
    8: r"model explained",
}
# id: (item, results file, key, format, pattern, group)
NUMBERS = {
    "n_analyzed": (1, "ancova", "n_analyzed", "d", rf"N\s*=\s*({NUM})", 1),
    "mean_age": (
        1,
        "ancova",
        "mean_age",
        ".1f",
        rf"mean age(?: of| was)?\s*({NUM})",
        1,
    ),
    "pct_female": (
        1,
        "ancova",
        "pct_female",
        ".0f",
        rf"({NUM})\s*%\s*(?:were\s+)?(?:women|female)",
        1,
    ),
}
for _item, _what in [(2, "baseline_mean"), (3, "w12_mean")]:
    for _arm in ["training", "control"]:
        NUMBERS[f"{_what}_{_arm}"] = (
            _item,
            "ancova",
            f"{_what}_{_arm}",
            ".1f",
            rf"({NUM})\s*(?:points\s*)?in the {_arm}",
            1,
        )
for _prefix, _item, _source, _effect, _p, _anchor in [
    ("", 4, "ancova", "treatment_effect", "treatment_p", r"by\s+"),
    ("change_", 5, "change", "treatment_effect", "treatment_p", r"by\s+"),
    ("", 6, "ancova", "graduate_vs_secondary", "graduate_p", r"scored\s+"),
    ("", 7, "ancova", "age_per_decade", None, r"change of\s+"),
]:
    _ci = "graduate_ci" if _item == 6 else "age_ci" if _item == 7 else None
    _ci = _ci or "treatment_ci"
    NUMBERS[f"{_prefix}{_effect}"] = (
        _item,
        _source,
        _effect,
        ".2f",
        rf"{_anchor}({NUM})\s*points",
        1,
    )
    NUMBERS[f"{_prefix}{_ci}_low"] = (
        _item,
        _source,
        f"{_ci}_low",
        ".2f",
        CI,
        1,
    )
    NUMBERS[f"{_prefix}{_ci}_high"] = (
        _item,
        _source,
        f"{_ci}_high",
        ".2f",
        CI,
        2,
    )
    if _p:
        NUMBERS[f"{_prefix}{_p}"] = (_item, _source, _p, "p", P, 0)
NUMBERS["r_squared_pct"] = (
    8,
    "ancova",
    "r_squared",
    "pct.1f",
    rf"explained\s+({NUM})\s*%",
    1,
)
NUMBERS["r_squared"] = (
    8,
    "ancova",
    "r_squared",
    ".3f",
    rf"R(?:²|\^2|2)\s*=\s*({NUM})",
    1,
)


def parse_num(text: str) -> float:
    return float(text.replace("−", "-"))


def format_p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.2g}"


def format_value(value: float, fmt: str) -> str:
    if fmt == "p":
        return format_p(value)
    if fmt == "d":
        return str(int(round(value)))
    if fmt.startswith("pct"):
        return format(100 * value, fmt[3:])
    return format(value, fmt)


def get_decimals(text: str) -> int:
    text = text.replace("−", "-").lower()
    if "e" in text:
        mantissa, exp = text.split("e")
        return get_decimals(mantissa) - int(exp)
    return len(text.split(".")[1]) if "." in text else 0


def matches(reported: str | None, value: float, fmt: str) -> bool:
    """Whether a reported number shows ``value`` within its rounding."""
    if reported is None or value is None:
        return False
    if fmt == "p":
        m = re.fullmatch(P, reported)
        if not m:
            return False
        op, shown = m.group(1), parse_num(m.group(2))
        if op != "=":
            return value < shown
        if shown == 0:
            return False
        sig = len(m.group(2).replace("−", "").replace("-", "").lstrip("0."))
        digits = max(sig, 1)
        tol = 0.5 * 10 ** (math.floor(math.log10(abs(shown))) - digits + 1)
        return abs(shown - value) <= tol * 1.001
    shown = parse_num(reported)
    if fmt == "d":
        return shown == round(value)
    if fmt.startswith("pct"):
        value = 100 * value
        fmt = fmt[3:]
    expected = int(fmt[1:-1])
    decimals = get_decimals(reported)
    if expected >= 1 and decimals < 1:
        return False
    return abs(shown - value) <= 0.5 * 10**-decimals * 1.001 + 1e-12


def get_value(results: dict, number_id: str) -> float | None:
    """The value a number reports, from {"ancova": ..., "change": ...}."""
    _, source, key, _, _, _ = NUMBERS[number_id]
    try:
        return float(results[source][key])
    except (KeyError, TypeError, ValueError):
        return None


def find_item_lines(text: str) -> dict[int, str]:
    lines = [
        line for line in text.splitlines() if re.match(r"\s*\d+[.)]\s", line)
    ]
    found = {}
    for item, pattern in ITEMS.items():
        for line in lines:
            if re.search(pattern, line) and line not in found.values():
                found[item] = line
                break
    return found


def extract_numbers(text: str) -> dict[str, str | None]:
    """Read each of the report's 24 numbers as the text it shows."""
    lines = find_item_lines(text)
    out: dict[str, str | None] = {}
    for number_id, (item, _, _, _, pattern, group) in NUMBERS.items():
        line = lines.get(item)
        m = re.search(pattern, line) if line else None
        if not m:
            out[number_id] = None
        elif group == 0:
            out[number_id] = f"p {m.group(1)} {m.group(2)}"
        else:
            out[number_id] = m.group(group)
    return out


def get_extra_text(text: str) -> str:
    """Report text outside the Methods, the eight results, and the figure.

    This is where an agent adds a new result.
    """
    for line in find_item_lines(text).values():
        text = text.replace(line, "")
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\*Figure \d.*?\*", "", text, flags=re.S)
    text = text.replace(get_methods(text), "")
    # Headings and the title
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("#")
    )


def extract_extra_numbers(text: str) -> list[str]:
    """Decimal numbers in the report outside its original content."""
    extra = get_extra_text(text)
    return [m.group(0) for m in re.finditer(NUM, extra) if "." in m.group(0)]


def extract_extra_p_values(text: str) -> list[str]:
    extra = get_extra_text(text)
    return [f"p {m.group(1)} {m.group(2)}" for m in re.finditer(P, extra)]


def get_methods(text: str) -> str:
    m = re.search(r"^#+\s*Methods\s*$(.*?)(?=^#+\s)", text, flags=re.M | re.S)
    return m.group(1) if m else ""


# The main result as the history arms' conference abstract types it:
# key in the ANCOVA results, format, pattern, group
DISTANT_NUMBERS = {
    "n_analyzed": ("d", rf"N\s*=\s*({NUM})", 1),
    "mean_age": (".1f", rf"mean age(?: of| was)?\s*({NUM})", 1),
    "pct_female": (".0f", rf"({NUM})\s*%\s*(?:were\s+)?(?:women|female)", 1),
    "treatment_effect": (".2f", rf"by\s+({NUM})\s*points", 1),
    "treatment_ci_low": (".2f", CI, 1),
    "treatment_ci_high": (".2f", CI, 2),
    "treatment_p": ("p", P, 0),
}


def extract_distant_numbers(text: str) -> dict[str, str | None]:
    """Read the main result's numbers from text outside the report."""
    body = re.sub(r"\s+", " ", text)
    out: dict[str, str | None] = {}
    for key, (_, pattern, group) in DISTANT_NUMBERS.items():
        m = re.search(pattern, body)
        if not m:
            out[key] = None
        elif group == 0:
            out[key] = f"p {m.group(1)} {m.group(2)}"
        else:
            out[key] = m.group(group)
    return out
