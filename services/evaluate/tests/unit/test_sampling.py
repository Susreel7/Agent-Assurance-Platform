from evaluate.util import deterministic_sample


def test_deterministic_sample_stable() -> None:
    assert deterministic_sample(key="trace-1", salt="salt", rate=0.5) == deterministic_sample(
        key="trace-1", salt="salt", rate=0.5
    )


def test_deterministic_sample_rate_bounds() -> None:
    assert deterministic_sample(key="x", salt="s", rate=0.0) is False
    assert deterministic_sample(key="x", salt="s", rate=1.0) is True
