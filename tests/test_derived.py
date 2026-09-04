"""The [[derived]] expression evaluator.

Config files are user-supplied text that gets evaluated, so the interesting
tests here are the ones about what it *refuses*.
"""

from __future__ import annotations

import math

import pytest

from wattop.core.derived import ExprError, compile_expr


def test_arithmetic_and_precedence():
    f = compile_expr("a + b * 2")
    assert f({"a": 1.0, "b": 3.0}) == 7.0


def test_dotted_channel_names_are_keys_not_attributes():
    f = compile_expr("emi.PSU_USB - emi.SYS - batt.power")
    assert f.names == {"emi.PSU_USB", "emi.SYS", "batt.power"}
    assert f({"emi.PSU_USB": 60.0, "emi.SYS": 14.0, "batt.power": 38.0}) == 8.0


def test_missing_input_yields_none_rather_than_raising():
    f = compile_expr("a / b")
    assert f({"a": 1.0}) is None


@pytest.mark.parametrize(
    "expr, sample",
    [
        ("a / b", {"a": 1.0, "b": 0.0}),          # ZeroDivisionError
        ("log(a)", {"a": -1.0}),                  # ValueError
        ("sqrt(a)", {"a": -1.0}),                 # ValueError
    ],
)
def test_arithmetic_failures_yield_none(expr, sample):
    assert compile_expr(expr)(sample) is None


def test_allowed_functions():
    assert compile_expr("max(a, b)")({"a": 1.0, "b": 2.0}) == 2.0
    assert compile_expr("abs(a)")({"a": -3.0}) == 3.0
    assert compile_expr("sqrt(a)")({"a": 9.0}) == 3.0
    assert compile_expr("log(a)")({"a": math.e}) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo pwned')",
        "().__class__.__bases__[0].__subclasses__()",
        "open('/etc/passwd').read()",
        "exec('x=1')",
        "eval('1')",
        "[a for a in range(3)]",
        "lambda: 1",
        "a if b else c",
        "'string'",
        "a = 1",
    ],
)
def test_rejects_anything_that_is_not_arithmetic(expr):
    """Nothing here should reach an interpreter. A rejection may surface as
    ExprError from the validator or SyntaxError from ast.parse in `eval` mode;
    both are refusals, and neither runs the payload."""
    with pytest.raises((ExprError, SyntaxError)):
        compile_expr(expr)


def test_unknown_function_is_rejected():
    with pytest.raises(ExprError):
        compile_expr("print(a)")
