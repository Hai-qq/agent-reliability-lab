"""Frozen blocked randomized schedules with a project-owned deterministic PRNG."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from arl.core.types import canonical_json, digest_value

PRNG_VERSION = "arl-sha256-counter-rejection-v1"


class _DeterministicRandom:
    def __init__(self, seed: int) -> None:
        if seed < 0:
            raise ValueError("schedule seed must be non-negative")
        self._seed = seed.to_bytes(max(1, (seed.bit_length() + 7) // 8), "big")
        self._counter = 0

    def _word(self) -> int:
        payload = self._seed + self._counter.to_bytes(16, "big")
        self._counter += 1
        return int.from_bytes(hashlib.sha256(payload).digest(), "big")

    def below(self, upper: int) -> int:
        if upper < 1:
            raise ValueError("upper must be positive")
        space = 1 << 256
        limit = space - (space % upper)
        while True:
            value = self._word()
            if value < limit:
                return value % upper

    def shuffle(self, values: list[Any]) -> None:
        for index in range(len(values) - 1, 0, -1):
            replacement = self.below(index + 1)
            values[index], values[replacement] = values[replacement], values[index]


@dataclass(frozen=True)
class ScheduleCell:
    """One unique study cell in its natural blocked population."""

    task_template_id: str
    environment_seed: int
    sampling_trial: int
    runtime: str
    condition: str
    model_slot: str

    @property
    def block_id(self) -> str:
        return canonical_json(
            {
                "environment_seed": self.environment_seed,
                "sampling_trial": self.sampling_trial,
                "task_template_id": self.task_template_id,
            }
        )

    @property
    def cell_id(self) -> str:
        return digest_value(asdict(self))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrozenSchedule:
    """Complete immutable execution order and balance diagnostics."""

    seed: int
    prng_version: str
    execution_order: tuple[ScheduleCell, ...]
    sha256: str
    balance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schedule_seed": self.seed,
            "prng_version": self.prng_version,
            "execution_order": [item.as_dict() for item in self.execution_order],
            "sha256": self.sha256,
            "balance": self.balance,
        }

    def remaining(self, completed_cell_ids: list[str]) -> tuple[ScheduleCell, ...]:
        """Resume only from an exact prefix of the frozen order."""

        expected_prefix = [item.cell_id for item in self.execution_order[: len(completed_cell_ids)]]
        if completed_cell_ids != expected_prefix:
            raise ValueError("completed cells are not an exact frozen-schedule prefix")
        return self.execution_order[len(completed_cell_ids) :]


def _balanced_runtime_order(
    cells: list[ScheduleCell], generator: _DeterministicRandom, previous_runtime: str | None
) -> list[ScheduleCell]:
    candidates = list(cells)
    generator.shuffle(candidates)
    ordered: list[ScheduleCell] = []
    last_runtime = previous_runtime
    while candidates:
        eligible = [index for index, item in enumerate(candidates) if item.runtime != last_runtime]
        selected_index = eligible[generator.below(len(eligible))] if eligible else 0
        selected = candidates.pop(selected_index)
        ordered.append(selected)
        last_runtime = selected.runtime
    return ordered


def _balance_diagnostics(order: list[ScheduleCell]) -> dict[str, Any]:
    counts = Counter((item.runtime, item.condition, item.model_slot) for item in order)
    block_counts: dict[str, int] = defaultdict(int)
    for item in order:
        block_counts[item.block_id] += 1
    max_streak = 0
    current_streak = 0
    previous: str | None = None
    for item in order:
        if item.runtime == previous:
            current_streak += 1
        else:
            current_streak = 1
            previous = item.runtime
        max_streak = max(max_streak, current_streak)
    values = list(counts.values())
    return {
        "cell_count": len(order),
        "block_count": len(block_counts),
        "cells_per_block": sorted(set(block_counts.values())),
        "runtime_condition_model_counts": {
            canonical_json({"runtime": key[0], "condition": key[1], "model_slot": key[2]}): value
            for key, value in sorted(counts.items())
        },
        "min_factorial_cell_count": min(values) if values else 0,
        "max_factorial_cell_count": max(values) if values else 0,
        "max_consecutive_same_runtime": max_streak,
        "balanced": bool(values) and min(values) == max(values),
    }


def blocked_randomized_schedule(
    *,
    task_template_ids: list[str],
    environment_seeds: list[int],
    sampling_trials: list[int],
    runtimes: list[str],
    conditions: list[str],
    model_slots: list[str],
    schedule_seed: int,
) -> FrozenSchedule:
    """Randomize the runtime/condition/model factorial within frozen task blocks."""

    factors: list[list[Any]] = [
        task_template_ids,
        environment_seeds,
        sampling_trials,
        runtimes,
        conditions,
        model_slots,
    ]
    if any(not values or len(set(values)) != len(values) for values in factors):
        raise ValueError("schedule factor lists must be non-empty and unique")
    generator = _DeterministicRandom(schedule_seed)
    blocks = [
        (task, seed, trial)
        for task in sorted(task_template_ids)
        for seed in sorted(environment_seeds)
        for trial in sorted(sampling_trials)
    ]
    generator.shuffle(blocks)
    order: list[ScheduleCell] = []
    for task, seed, trial in blocks:
        block = [
            ScheduleCell(task, seed, trial, runtime, condition, model)
            for runtime in sorted(runtimes)
            for condition in sorted(conditions)
            for model in sorted(model_slots)
        ]
        previous = order[-1].runtime if order else None
        order.extend(_balanced_runtime_order(block, generator, previous))
    payload = [item.as_dict() for item in order]
    balance = _balance_diagnostics(order)
    if not balance["balanced"]:
        raise RuntimeError("generated schedule is not factorially balanced")
    return FrozenSchedule(
        seed=schedule_seed,
        prng_version=PRNG_VERSION,
        execution_order=tuple(order),
        sha256=digest_value(payload),
        balance=balance,
    )
