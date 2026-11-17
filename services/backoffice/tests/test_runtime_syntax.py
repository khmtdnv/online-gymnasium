"""Сохраняет заявленную поддержку Python3.12 после форматирования py314."""

import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "student_class_views.py",
        "student_period_views.py",
        "user_views.py",
        "teacher_class_views.py",
    ],
)
def test_view_exception_syntax_supports_python_312(module):
    path = Path(__file__).parents[1] / "src/backoffice_admin" / module
    ast.parse(path.read_text(), filename=module, feature_version=(3, 12))
