"""Methodology diagnostics for published and legacy analysis records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def conditional_denominator_diagnostic(result: Mapping[str, Any]) -> dict[str, Any]:
    """Flag the legacy conditional estimand when its clean strata differ."""

    r1 = result.get("r1", {})
    r2 = result.get("r2", {})
    r1_denominator = r1.get("denominator") if isinstance(r1, Mapping) else None
    r2_denominator = r2.get("denominator") if isinstance(r2, Mapping) else None
    return {
        "diagnostic": "runtime_specific_clean_denominator_comparability",
        "r1_denominator": r1_denominator,
        "r2_denominator": r2_denominator,
        "denominators_equal": r1_denominator == r2_denominator,
        "descriptive_only": True,
        "primary_estimand_allowed": False,
    }
