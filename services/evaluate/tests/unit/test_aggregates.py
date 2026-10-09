from evaluate.stats.aggregates import bootstrap_mean_ci, compare_to_baseline


def test_bootstrap_ci() -> None:
    ci = bootstrap_mean_ci([0.5, 0.6, 0.7, 0.8], seed=1)
    assert ci["n"] == 4
    assert ci["ci_low"] <= ci["mean"] <= ci["ci_high"]


def test_regression_compare() -> None:
    cmp = compare_to_baseline([0.5, 0.5], [0.9, 0.9], regression_threshold=0.1)
    assert cmp["regressed"] is True
