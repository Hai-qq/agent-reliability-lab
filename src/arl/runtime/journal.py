"""Deterministic append-only event journal with digest-only payload evidence."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json


@dataclass(frozen=True)
class TraceEvent:
    run_id: str
    episode_id: str
    task_id: str
    seed: int
    event_id: str
    parent_event_id: str | None
    timestamp_logical: int
    actor: str
    event_type: str
    input_digest: str | None
    output_digest: str | None
    tool_name: str | None
    schema_version: str | None
    latency_ms: int
    token_usage: int
    monetary_cost: float
    state_hash_before: str
    state_hash_after: str
    error_code: str | None
    fault_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventJournal:
    """Keep deterministic events in memory and optionally persist JSONL."""

    def __init__(
        self,
        *,
        run_id: str,
        episode_id: str,
        task_id: str,
        seed: int,
        path: Path | None = None,
    ) -> None:
        if path is not None and path.exists():
            raise FileExistsError(f"Refusing to overwrite trace: {path}")
        self.run_id = run_id
        self.episode_id = episode_id
        self.task_id = task_id
        self.seed = seed
        self.path = path
        self._events: list[TraceEvent] = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [event.as_dict() for event in self._events]

    def append(
        self,
        *,
        timestamp_logical: int,
        actor: str,
        event_type: str,
        state_hash_before: str,
        state_hash_after: str,
        input_digest: str | None = None,
        output_digest: str | None = None,
        tool_name: str | None = None,
        schema_version: str | None = None,
        error_code: str | None = None,
        fault_id: str | None = None,
    ) -> TraceEvent:
        sequence = len(self._events) + 1
        parent_event_id = self._events[-1].event_id if self._events else None
        event = TraceEvent(
            run_id=self.run_id,
            episode_id=self.episode_id,
            task_id=self.task_id,
            seed=self.seed,
            event_id=f"{self.episode_id}:{sequence:04d}",
            parent_event_id=parent_event_id,
            timestamp_logical=timestamp_logical,
            actor=actor,
            event_type=event_type,
            input_digest=input_digest,
            output_digest=output_digest,
            tool_name=tool_name,
            schema_version=schema_version,
            latency_ms=0,
            token_usage=0,
            monetary_cost=0.0,
            state_hash_before=state_hash_before,
            state_hash_after=state_hash_after,
            error_code=error_code,
            fault_id=fault_id,
        )
        self._events.append(event)
        if self.path is not None:
            line = canonical_json(event.as_dict()) + "\n"
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        return event

    def jsonl_bytes(self) -> bytes:
        return b"".join(
            (canonical_json(event.as_dict()) + "\n").encode("utf-8") for event in self._events
        )
