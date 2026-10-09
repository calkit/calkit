"""Conditions written in ``calkit.yaml``, and ``if``/``elif``/``else``
mappings that pick a value with them.

A condition is a restricted Python expression: comparisons, ``in``,
``and``/``or``/``not`` and arithmetic. Nothing can be called, so a
condition read from a project cannot run arbitrary code.
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
_ARITHMETIC: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.Compare,
    ast.BinOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.List,
    ast.Tuple,
    *_COMPARISONS,
    *_ARITHMETIC,
    *_UNARY,
)
# Bounds that keep a condition from exhausting time or memory
_MAX_INT_BITS = 10_000
_MAX_LENGTH = 10_000


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


def check_condition(expression: str) -> ast.Expression:
    """Parse a condition, refusing anything evaluating it would refuse."""
    shown = expression if len(expression) <= 200 else expression[:200] + "..."
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, MemoryError, RecursionError) as e:
        raise ValueError(f"cannot parse condition {shown!r}: {e}") from e

    def refuse(problem: str) -> ValueError:
        return ValueError(f"condition {shown!r}: {problem}")

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            if isinstance(node, ast.expr):
                what = f"{type(node).__name__} {ast.unparse(node)!r}"
            else:
                what = type(node).__name__
            raise refuse(f"{what} is not allowed")
    return tree


def _arithmetic(node: ast.AST, values: dict[str, Any]) -> Any:
    """A value computed from names and literals, within size bounds."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise KeyError(node.id)
        return values[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_arithmetic(node.operand, values))
    if not isinstance(node, ast.BinOp) or type(node.op) not in _ARITHMETIC:
        raise ValueError(f"{ast.unparse(node)!r} is not supported")
    left = _arithmetic(node.left, values)
    right = _arithmetic(node.right, values)
    op = type(node.op)
    ints = isinstance(left, int) and isinstance(right, int)
    if op is ast.Pow and ints and right > 0:
        if abs(left).bit_length() * right > _MAX_INT_BITS:
            raise ValueError(f"{ast.unparse(node)!r} is too large")
    if op is ast.Mult:
        for seq, count in ((left, right), (right, left)):
            if isinstance(seq, (str, bytes, list, tuple)) and isinstance(
                count, int
            ):
                if len(seq) * count > _MAX_LENGTH:
                    raise ValueError(f"{ast.unparse(node)!r} is too long")
    if op is ast.Mod and isinstance(left, (str, bytes)):
        raise ValueError("string formatting is not supported")
    return _ARITHMETIC[op](left, right)


def _operand(node: ast.AST, values: dict[str, Any]) -> Any:
    """One side of a comparison, resolved against the values."""
    if isinstance(node, ast.List):
        return [_operand(e, values) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_operand(e, values) for e in node.elts)
    # A missing name is reported before anything else, so a name that
    # isn't an identifier gets the message saying so
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and inner.id not in values:
            raise KeyError(inner.id)
    return _arithmetic(node, values)


def _truth(node: ast.AST, values: dict[str, Any]) -> bool:
    if isinstance(node, ast.BoolOp):
        # Not short-circuited, so a misspelled name is an error whatever
        # the current values are
        outcomes = [_truth(v, values) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(outcomes)
        return any(outcomes)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _truth(node.operand, values)
    if isinstance(node, ast.Compare):
        left = _operand(node.left, values)
        for op, comparator in zip(node.ops, node.comparators):
            right = _operand(comparator, values)
            compare = _COMPARISONS.get(type(op))
            if compare is None:
                raise ValueError(
                    f"{type(op).__name__} is not a supported comparison"
                )
            if not compare(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        value = _operand(node, values)
        # Only a true/false value stands alone, so a number is never
        # silently read as its truthiness
        if isinstance(value, bool):
            return value
    raise ValueError(
        "a condition must compare values, e.g., 'p < 0.05', "
        "or name a true/false value"
    )


def evaluate_condition(expression: str, values: dict[str, Any]) -> bool:
    """Evaluate one ``if``/``elif`` condition against ``values``.

    Raises ``KeyError`` for a name not in ``values`` and ``ValueError``
    for anything else wrong with the condition.
    """

    def unusable_name() -> ValueError | None:
        # A name like 'paired-gain.vawt-8' reads as arithmetic and
        # attribute access, so the failure would otherwise name a
        # fragment of it or a construct that isn't allowed
        unusable = [
            name
            for name in values
            if not name.isidentifier() and name in expression
        ]
        if not unusable:
            return None
        return ValueError(
            f"condition {expression!r} refers to {unusable[0]!r}, which "
            "cannot be read as a variable; give it a 'name' that is a "
            "valid Python identifier"
        )

    try:
        tree = check_condition(expression)
    except ValueError:
        error = unusable_name()
        if error is not None:
            raise error from None
        raise
    try:
        return bool(_truth(tree.body, values))
    except KeyError:
        error = unusable_name()
        if error is not None:
            raise error from None
        raise
    except ValueError as e:
        raise ValueError(f"condition {expression!r}: {e}") from e
    except Exception as e:
        # E.g., comparing a string to a number, or a value too deeply nested
        # to evaluate, so callers only have to handle one kind of bad
        # condition
        raise ValueError(
            f"cannot evaluate condition {expression!r}: {e}"
        ) from e


def select_branch(clauses: dict, values: dict[str, Any]) -> str:
    """The value whose condition holds first."""
    for condition, wording in parse_conditional(clauses):
        if condition is None or evaluate_condition(condition, values):
            return wording
    raise ValueError("no condition held and there is no 'else' clause")
