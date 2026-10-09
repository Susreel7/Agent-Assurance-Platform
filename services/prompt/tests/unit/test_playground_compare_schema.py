from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from prompt.domains.playground.schemas import (
    ArtifactRef,
    PlaygroundCompareOutput,
    PlaygroundRunRequest,
)


def test_compare_mode_requires_two_artifacts() -> None:
    with pytest.raises(ValidationError, match="at least two"):
        PlaygroundRunRequest(
            mode="compare",
            artifacts=[ArtifactRef(revision_id=uuid4())],
            model_alias="m",
        )


def test_compare_output_schema_example() -> None:
    out = PlaygroundCompareOutput.model_validate(
        {
            "variants": [
                {"trace": {"x-request-id": "a"}, "response": {"choices": []}},
                {"error": "router returned 503"},
            ]
        }
    )
    assert len(out.variants) == 2
