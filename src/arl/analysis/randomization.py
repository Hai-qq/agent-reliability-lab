"""Exact paired binary-outcome sensitivity calculations."""

from __future__ import annotations

import math


def exact_mcnemar_p_value(n_r1_fail_r2_pass: int, n_r1_pass_r2_fail: int) -> float:
    """Return the two-sided exact McNemar binomial p-value."""

    if n_r1_fail_r2_pass < 0 or n_r1_pass_r2_fail < 0:
        raise ValueError("paired counts must be non-negative")
    discordant = n_r1_fail_r2_pass + n_r1_pass_r2_fail
    if discordant == 0:
        return 1.0
    smaller = min(n_r1_fail_r2_pass, n_r1_pass_r2_fail)
    lower_tail = sum(math.comb(discordant, index) for index in range(smaller + 1)) / (2**discordant)
    return float(min(1.0, 2 * lower_tail))


def paired_counts(pairs: list[tuple[bool, bool]]) -> dict[str, int]:
    """Return the complete R1-by-R2 2x2 table."""

    return {
        "r1_fail_r2_fail": sum(not first and not second for first, second in pairs),
        "r1_fail_r2_pass": sum(not first and second for first, second in pairs),
        "r1_pass_r2_fail": sum(first and not second for first, second in pairs),
        "r1_pass_r2_pass": sum(first and second for first, second in pairs),
    }
