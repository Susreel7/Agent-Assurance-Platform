"""Experiment aggregates and simple bootstrap confidence."""

from __future__ import annotations

import math
import random
from typing import Any


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def bootstrap_mean_ci(
    values: list[float],
    *,
    samples: int = 500,
    alpha: float = 0.05,
    seed: int = 0,
) -> dict[str, Any]:
    if len(values) < 2:
        m = mean(values)
        return {"mean": m, "ci_low": m, "ci_high": m, "n": len(values)}
    rng = random.Random(seed)
    boots: list[float] = []
    n = len(values)
    for _ in range(samples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        boots.append(sum(sample) / n)
    boots.sort()
    lo_idx = max(0, int((alpha / 2) * len(boots)) - 1)
    hi_idx = min(len(boots) - 1, int((1 - alpha / 2) * len(boots)))
    return {
        "mean": mean(values),
        "ci_low": boots[lo_idx],
        "ci_high": boots[hi_idx],
        "n": n,
    }


def compare_to_baseline(
    candidate: list[float],
    baseline: list[float],
    *,
    regression_threshold: float,
) -> dict[str, Any]:
    c_mean = mean(candidate) or 0.0
    b_mean = mean(baseline) or 0.0
    delta = c_mean - b_mean
    regressed = delta < -abs(regression_threshold)
    improved = delta > abs(regression_threshold)
    return {
        "candidate_mean": c_mean,
        "baseline_mean": b_mean,
        "delta": delta,
        "regressed": regressed,
        "improved": improved,
        "threshold": regression_threshold,
    }


def aggregate_experiment_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_metric: dict[str, list[float]] = {}
    for row in rows:
        scores = row.get("scores") or {}
        if not isinstance(scores, dict):
            continue
        for name, val in scores.items():
            if isinstance(val, dict) and "score" in val:
                try:
                    by_metric.setdefault(str(name), []).append(float(val["score"]))
                except (TypeError, ValueError):
                    continue
            elif isinstance(val, (int, float)):
                by_metric.setdefault(str(name), []).append(float(val))
    out: dict[str, Any] = {}
    for name, vals in by_metric.items():
        out[name] = {
            "mean": mean(vals),
            "count": len(vals),
            "bootstrap": bootstrap_mean_ci(vals),
        }
    return out


def stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values) or 0.0
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)
