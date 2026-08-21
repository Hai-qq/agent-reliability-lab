"""Deterministic task-template cluster bootstrap utilities."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from typing import TypeVar

T = TypeVar("T")


def percentile(values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated empirical percentile."""

    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0, 1]")
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def cluster_bootstrap(
    clusters: Mapping[str, Sequence[T]],
    statistic: Callable[[Sequence[T]], float],
    *,
    seed: int,
    iterations: int,
    alpha: float = 0.05,
) -> dict[str, float | int | str]:
    """Resample whole task-template clusters and retain every nested paired cell."""

    if iterations < 1:
        raise ValueError("iterations must be positive")
    if not clusters:
        raise ValueError("cluster bootstrap requires at least one cluster")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    names = sorted(clusters)
    generator = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        sampled: list[T] = []
        for _index in range(len(names)):
            sampled.extend(clusters[generator.choice(names)])
        estimates.append(statistic(sampled))
    return {
        "method": "task_template_cluster_percentile_bootstrap",
        "cluster_definition": (
            "task_template_id; resample retains all seeds, trials, runtimes, "
            "conditions, and model slots"
        ),
        "resample_seed": seed,
        "iteration_count": iterations,
        "confidence_level": 1 - alpha,
        "lower": percentile(estimates, alpha / 2),
        "upper": percentile(estimates, 1 - alpha / 2),
    }
