from __future__ import annotations

import pytest

from prompt.errors import ValidationError
from prompt.validation.variables import extract_variable_names, validate_variables_against_schema


def test_jinja_variables_without_execution() -> None:
    names = extract_variable_names("Hello {{ user_name }}!")
    assert names == {"user_name"}


def test_jinja_blocks_rejected() -> None:
    with pytest.raises(ValidationError):
        extract_variable_names("{% if x %}bad{% endif %}")


def test_variable_schema_enforced() -> None:
    with pytest.raises(ValidationError):
        validate_variables_against_schema({"missing"}, None)
