"""Config-declared derived channels.

    [[derived]]
    key = "batt.current"; unit = "A"; expr = "batt.power / batt.voltage"

Expressions are evaluated against the current sample. Only arithmetic, a short
list of maths functions and channel names are allowed -- this parses the AST and
walks it rather than handing anything to bare `eval`.
"""

from __future__ import annotations

import ast
import math
import operator

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
    "log": math.log,
}


class ExprError(ValueError):
    pass


def compile_expr(expr: str):
    """Return a callable `sample -> float | None`, or raise ExprError."""
    try:
        tree = ast.parse(expr, mode="eval").body
    except SyntaxError as exc:  # pragma: no cover - config typo path
        raise ExprError(f"cannot parse {expr!r}: {exc}") from exc

    names: set[str] = set()
    _validate(tree, names)

    def evaluate(sample: dict[str, float]) -> float | None:
        # A derived value is only as available as its inputs.
        if any(n not in sample for n in names):
            return None
        try:
            return float(_eval(tree, sample))
        except (ZeroDivisionError, ValueError, OverflowError):
            return None

    evaluate.names = names  # type: ignore[attr-defined]
    return evaluate


def _dotted(node: ast.AST) -> str | None:
    """Channel keys are dotted (`batt.power`), so Python parses them as
    attribute access. Flatten that back into the key string."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _validate(node: ast.AST, names: set[str]) -> None:
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise ExprError("only numeric constants are allowed")
    elif isinstance(node, ast.Name):
        names.add(node.id)
    elif isinstance(node, ast.Attribute):
        key = _dotted(node)
        if key is None:
            raise ExprError("only plain dotted channel keys may be referenced")
        names.add(key)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOPS:
            raise ExprError(f"operator {type(node.op).__name__} is not allowed")
        _validate(node.left, names)
        _validate(node.right, names)
    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARYOPS:
            raise ExprError(f"operator {type(node.op).__name__} is not allowed")
        _validate(node.operand, names)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ExprError("only abs/min/max/round/sqrt/log may be called")
        if node.keywords:
            raise ExprError("keyword arguments are not allowed")
        for arg in node.args:
            _validate(arg, names)
    else:
        raise ExprError(f"{type(node).__name__} is not allowed in an expression")


def _eval(node: ast.AST, sample: dict[str, float]):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return sample[node.id]
    if isinstance(node, ast.Attribute):
        return sample[_dotted(node)]  # type: ignore[index]
    if isinstance(node, ast.BinOp):
        return _BINOPS[type(node.op)](_eval(node.left, sample), _eval(node.right, sample))
    if isinstance(node, ast.UnaryOp):
        return _UNARYOPS[type(node.op)](_eval(node.operand, sample))
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)
        return _FUNCS[node.func.id](*[_eval(a, sample) for a in node.args])
    raise ExprError("unreachable")  # pragma: no cover
