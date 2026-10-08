"""Conditions written in ``calkit.yaml``, and ``if``/``elif``/``else``
mappings that pick a value with them.

A condition is a restricted Python expression: comparisons, ``in``,
``and``/``or``/``not``, arithmetic, and calls to functions the caller
allows by name. Nothing else can be called, so a condition read from a
project cannot run arbitrary code.
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Any, Callable, TypeGuard

_IF_KEY = re.compile(r"^\s*(if|elif)\s+(.+?)\s*$")
_ELSE_KEY = re.compile(r"^\s*else\s*$")
_COMPARISONS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def is_conditional(value: Any) -> TypeGuard[dict]:
    """Whether a value is picked with ``if``/``elif``/``else``."""
    return isinstance(value, dict)


def parse_conditional(clauses: dict) -> list[tuple[str | None, str]]:
    """Read a conditional's keys into ordered ``(condition, value)``.

    The condition is ``None`` for ``else``. Keys are read in the order
    they appear in the file, so the clauses are tried in the order they
    were written.
    """
    parsed: list[tuple[str | None, str]] = []
    for position, (key, wording) in enumerate(clauses.items()):
        opened = _IF_KEY.match(str(key))
        if opened:
            keyword, condition = opened.groups()
            if keyword == "if" and position:
                raise ValueError("only the first clause may be 'if'")
            if keyword == "elif" and not parsed:
                raise ValueError("'elif' with no 'if' before it")
            parsed.append((condition, str(wording)))
            continue
        if _ELSE_KEY.match(str(key)):
            if not parsed:
                raise ValueError("'else' with no 'if' before it")
            parsed.append((None, str(wording)))
            continue
        raise ValueError(f"expected 'if', 'elif' or 'else', got {key!r}")
    if not parsed:
        raise ValueError("a conditional needs at least an 'if' clause")
    for condition, _ in parsed[:-1]:
        if condition is None:
            raise ValueError("'else' must be the last clause")
    return parsed


def _call(
    node: ast.Call,
    values: dict[str, Any],
    functions: dict[str, Callable],
) -> Any:
    if not isinstance(node.func, ast.Name) or node.func.id not in functions:
        name = ast.unparse(node.func)
        allowed = ", ".join(sorted(functions)) or "none"
        raise ValueError(
            f"'{name}' cannot be called in a condition (allowed: {allowed})"
        )
    if node.keywords:
        raise ValueError("keyword arguments are not supported in conditions")
    args = [_operand(a, values, functions) for a in node.args]
    return functions[node.func.id](*args)


def _operand(
    node: ast.AST,
    values: dict[str, Any],
    functions: dict[str, Callable],
) -> Any:
    """One side of a comparison, resolved against the values.

    Names, literals and allowed calls are read directly; anything else is
    arithmetic and goes to the same evaluator the calculations use, so
    there is one audited path for arithmetic rather than two.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise KeyError(node.id)
        return values[node.id]
    if isinstance(node, ast.Call):
        return _call(node, values, functions)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_operand(e, values, functions) for e in node.elts]
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            raise ValueError(
                "a call can be compared, but not used inside arithmetic"
            )
        if isinstance(inner, ast.Name) and inner.id not in values:
            raise KeyError(inner.id)
    import arithmetic_eval  # type: ignore[import-untyped]

    return arithmetic_eval.evaluate(ast.unparse(node), values)


def _truth(
    node: ast.AST,
    values: dict[str, Any],
    functions: dict[str, Callable],
) -> bool:
    if isinstance(node, ast.BoolOp):
        # Not short-circuited, so a misspelled name is an error whatever
        # the current values are
        outcomes = [_truth(v, values, functions) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(outcomes)
        return any(outcomes)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _truth(node.operand, values, functions)
    if isinstance(node, ast.Compare):
        left = _operand(node.left, values, functions)
        for op, comparator in zip(node.ops, node.comparators):
            right = _operand(comparator, values, functions)
            compare = _COMPARISONS.get(type(op))
            if compare is None:
                raise ValueError(
                    f"{type(op).__name__} is not a supported comparison"
                )
            if not compare(left, right):
                return False
            left = right
        return True
    if isinstance(node, (ast.Name, ast.Call)):
        value = _operand(node, values, functions)
        # Only a true/false value stands alone, so a number is never
        # silently read as its truthiness
        if isinstance(value, bool):
            return value
    raise ValueError(
        "a condition must compare values, e.g., 'p < 0.05', "
        "or name a true/false value"
    )


def evaluate_condition(
    expression: str,
    values: dict[str, Any],
    functions: dict[str, Callable] | None = None,
) -> bool:
    """Evaluate one ``if``/``elif`` condition against ``values``.

    Raises ``KeyError`` for a name not in ``values`` and ``ValueError``
    for anything else wrong with the condition.
    """
    if functions is None:
        functions = {}
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"cannot parse condition {expression!r}: {e}") from e
    try:
        return bool(_truth(tree.body, values, functions))
    except KeyError:
        # A name like 'paired-gain.vawt-8' reads as arithmetic and
        # attribute access, so the failure would otherwise name a
        # fragment of it and look like a missing value
        unusable = [
            name
            for name in values
            if not name.isidentifier() and name in expression
        ]
        if unusable:
            raise ValueError(
                f"condition {expression!r} refers to {unusable[0]!r}, which "
                "cannot be read as a variable; give it a 'name' that is a "
                "valid Python identifier"
            ) from None
        raise
    except ValueError:
        raise
    except Exception as e:
        # E.g., comparing a string to a number, or syntax arithmetic_eval
        # refuses, so callers only have to handle one kind of bad condition
        raise ValueError(
            f"cannot evaluate condition {expression!r}: {e}"
        ) from e


def select_branch(
    clauses: dict,
    values: dict[str, Any],
    functions: dict[str, Callable] | None = None,
) -> str:
    """The value whose condition holds first."""
    for condition, wording in parse_conditional(clauses):
        if condition is None or evaluate_condition(
            condition, values, functions=functions
        ):
            return wording
    raise ValueError("no condition held and there is no 'else' clause")
