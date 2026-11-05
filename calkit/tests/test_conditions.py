"""Tests for ``calkit.conditions``."""

import pytest

from calkit.conditions import (
    evaluate_condition,
    parse_conditional,
    select_branch,
)


def test_evaluate_condition():
    values = {"p": 0.007, "rho": 0.8373, "n": 17, "leader": "turns-max"}
    # Comparisons, chaining, boolean operators, strings, and arithmetic
    assert evaluate_condition("p < 0.05", values)
    assert not evaluate_condition("p >= 0.05", values)
    assert evaluate_condition("0.0 <= p < 0.05", values)
    assert evaluate_condition("p < 0.05 and rho > 0.8", values)
    assert evaluate_condition("p > 0.5 or rho > 0.8", values)
    assert evaluate_condition("not p > 0.5", values)
    assert evaluate_condition("leader == 'turns-max'", values)
    assert evaluate_condition("n / 2 > 8", values)
    # A name with no evidence is an error, not a false condition, and
    # nothing may be called or used as a bare value
    with pytest.raises(KeyError):
        evaluate_condition("missing < 1", values)
    with pytest.raises(ValueError, match="Call 'len\\(leader\\)'"):
        evaluate_condition("len(leader) > 1", values)
    with pytest.raises(ValueError):
        evaluate_condition("p", values)
    # A true/false value can stand alone, e.g., a 'passes' flag in results
    flags = {"ok": True, "bad": False, "p": 0.007}
    assert evaluate_condition("ok", flags)
    assert evaluate_condition("ok and not bad", flags)
    assert not evaluate_condition("bad or p > 0.5", flags)
    with pytest.raises(ValueError, match="true/false"):
        evaluate_condition("ok and p", flags)
    with pytest.raises(KeyError):
        evaluate_condition("missing", flags)
    # A comparison the values can't make is a ValueError like the rest
    with pytest.raises(ValueError, match="cannot evaluate"):
        evaluate_condition("leader < 0.5", values)
    # A name that is not a valid identifier cannot be read as a variable,
    # and says so rather than reporting a fragment of itself as missing
    with pytest.raises(ValueError, match="valid Python identifier"):
        evaluate_condition("paired-gain > 0.1", {"paired-gain": 0.25})
    # Clauses are tried in the order written, with None marking the else
    clauses = {
        "if p < 0.05": "strong, rho {rho:.2f}",
        "elif p < 0.1": "weak",
        "else": "none",
    }
    assert [c for c, _ in parse_conditional(clauses)] == [
        "p < 0.05",
        "p < 0.1",
        None,
    ]
    assert select_branch(clauses, {"p": 0.007}) == "strong, rho {rho:.2f}"
    assert select_branch(clauses, {"p": 0.08}) == "weak"
    assert select_branch(clauses, {"p": 0.9}) == "none"
    # Malformed clause sets are errors rather than silent misreadings
    with pytest.raises(ValueError):
        parse_conditional({"elif p < 1": "x"})
    with pytest.raises(ValueError):
        parse_conditional({"else": "x"})
    with pytest.raises(ValueError):
        parse_conditional({"when p < 1": "x"})
    with pytest.raises(ValueError):
        parse_conditional({"if p < 1": "x", "else": "y", "elif p < 2": "z"})
    with pytest.raises(ValueError):
        parse_conditional({"if p < 1": "x", "if p < 2": "y"})
    # Nothing holding with no else is an error rather than a blank answer
    with pytest.raises(ValueError):
        select_branch({"if p < 0.05": "strong"}, {"p": 0.9})
    # Membership works on strings, lists and tuples
    assert evaluate_condition("'turns' in leader", values)
    assert evaluate_condition("n not in [1, 2]", values)
    assert evaluate_condition("17 in (n, 1)", values)
    # A tuple stays a tuple, so it equals a tuple value but not a list
    assert evaluate_condition("pair == (1, 2)", {"pair": (1, 2)})
    assert not evaluate_condition("pair == (1, 2)", {"pair": [1, 2]})
    # Arithmetic, including negation and powers, within bounds
    assert evaluate_condition("n * -2 < 0 and 2 ** 10 == 1024", values)
    assert evaluate_condition("'ab' * 2 == 'abab'", values)
    # Anything outside comparisons, arithmetic, names and literals is
    # refused, whether or not it could be evaluated
    refused = {
        "'x'.upper() == 'X'": "Call",
        "leader.__class__ == 1": "Attribute 'leader.__class__'",
        "leader[0] == 't'": "Subscript",
        "[c for c in leader] == []": "ListComp",
        "(lambda: 1)() == 1": "Call",
        "n | 1 == 1": "BitOr",
        "9 ** 9 ** 9 > 1": "too large",
        "'a' * 10 ** 9 == ''": "too long",
        "'%0999999999d' % 1 == ''": "string formatting",
        "-" * 100000 + "1": "cannot parse",
    }
    for expression, problem in refused.items():
        with pytest.raises(ValueError, match=problem):
            evaluate_condition(expression, values)
    # The structure is refused before any name is looked up, and a missing
    # name is an error even past a comparison that's already false
    for expression in ("leader.__class__ == 1", "len(x) > 1", "p <"):
        with pytest.raises(ValueError, match="condition"):
            evaluate_condition(expression, {})
    with pytest.raises(KeyError):
        evaluate_condition("n < 1 < missing", values)
    # Deep nesting and overflow are reported like any other bad condition
    deep = "abs(" + "1+" * 1000 + "1) < 0"
    with pytest.raises(ValueError, match="Call 'abs"):
        evaluate_condition(deep, {})
    with pytest.raises(ValueError, match="too large"):
        evaluate_condition("2.0 ** 10000 > 1", {})
