"""Workspace v0.2 environment with atomic idempotency and post-commit faults."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from arl.core.types import (
    Observation,
    SnapshotRef,
    StepResult,
    ToolAction,
    canonical_json,
    digest_value,
)
from arl.envs.workspace import (
    ENV_VERSION as BASE_ENV_VERSION,
)
from arl.envs.workspace import (
    SCHEMA_VERSION,
    WorkspaceEnvironment,
)

ENV_VERSION = "workspace-v0.2.0"
FaultMode = Literal["none", "event_postcommit_timeout_once"]


class ReliableWorkspaceEnvironment(WorkspaceEnvironment):
    """Extend the v0.1 world without changing its historical implementation."""

    def __init__(self, fault_mode: FaultMode = "none") -> None:
        if fault_mode not in {"none", "event_postcommit_timeout_once"}:
            raise ValueError(f"Unknown fault mode: {fault_mode}")
        super().__init__(fault_mode="none")
        self.r2_fault_mode = fault_mode
        self._connection.execute(
            """
            CREATE TABLE idempotency_records (
                idempotency_key TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                result_json TEXT NOT NULL,
                committed_state_version INTEGER NOT NULL
            )
            """
        )

    def reset(self, task_id: str, seed: int) -> Observation:
        self._connection.execute("DELETE FROM idempotency_records")
        observation = super().reset(task_id, seed)
        return Observation(
            task_id=observation.task_id,
            seed=observation.seed,
            env_version=ENV_VERSION,
            state_version=observation.state_version,
            timestamp_logical=observation.timestamp_logical,
            state_hash=self.state_hash(),
            visible_task=observation.visible_task,
        )

    def _idempotency_rows(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT idempotency_key, tool_name, request_digest, result_json,
                   committed_state_version
            FROM idempotency_records
            ORDER BY idempotency_key
            """
        ).fetchall()
        return [
            {
                "idempotency_key": row["idempotency_key"],
                "tool_name": row["tool_name"],
                "request_digest": row["request_digest"],
                "result": json.loads(row["result_json"]),
                "committed_state_version": row["committed_state_version"],
            }
            for row in rows
        ]

    def export_world(self) -> dict[str, Any]:
        world = super().export_world()
        world["env_version"] = ENV_VERSION
        world["idempotency_records"] = self._idempotency_rows()
        return world

    def snapshot(self) -> SnapshotRef:
        return SnapshotRef.from_value(
            {
                "world": self.export_world(),
                "runtime": {
                    "logical_time": self._logical_time,
                    "fault_attempts": dict(sorted(self._fault_attempts.items())),
                },
            }
        )

    def restore(self, snapshot: SnapshotRef) -> None:
        payload = snapshot.load()
        world = payload["world"]
        if world["env_version"] != ENV_VERSION:
            raise ValueError("Snapshot environment version mismatch")
        records = world["idempotency_records"]
        base_world = dict(world)
        base_world.pop("idempotency_records")
        base_world["env_version"] = BASE_ENV_VERSION
        self._connection.execute("DELETE FROM idempotency_records")
        super().restore(
            SnapshotRef.from_value(
                {
                    "world": base_world,
                    "runtime": payload["runtime"],
                }
            )
        )
        self._connection.executemany(
            """
            INSERT INTO idempotency_records(
                idempotency_key, tool_name, request_digest, result_json,
                committed_state_version
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    record["idempotency_key"],
                    record["tool_name"],
                    record["request_digest"],
                    canonical_json(record["result"]),
                    record["committed_state_version"],
                )
                for record in records
            ],
        )

    @staticmethod
    def _request_digest(action: ToolAction) -> str:
        return digest_value(
            {
                "tool_name": action.tool_name,
                "schema_version": action.schema_version,
                "arguments": action.arguments,
            }
        )

    def _idempotency_replay(self, action: ToolAction, before_hash: str) -> StepResult | None:
        if action.idempotency_key is None:
            return None
        if not isinstance(action.idempotency_key, str) or not action.idempotency_key.strip():
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_idempotency_key",
            )
        row = self._connection.execute(
            """
            SELECT tool_name, request_digest, result_json
            FROM idempotency_records
            WHERE idempotency_key = ?
            """,
            (action.idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row["tool_name"] != action.tool_name or row["request_digest"] != self._request_digest(
            action
        ):
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="idempotency_key_reused",
            )
        return self._result(
            status="ok",
            before_hash=before_hash,
            value=json.loads(row["result_json"]),
        )

    def _validate_action(self, action: ToolAction, before_hash: str) -> StepResult | None:
        if action.schema_version != SCHEMA_VERSION:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="schema_version_unsupported",
            )
        if action.tool_name not in {
            "calendar.create_event",
            "calendar.get_event",
            "messages.send_invitations",
        }:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="unknown_tool",
            )
        if action.tool_name == "calendar.create_event":
            replay = self._idempotency_replay(action, before_hash)
            if replay is not None:
                return replay
        if (
            action.expected_state_version is not None
            and action.expected_state_version != self._state_version
        ):
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="state_version_conflict",
            )
        return None

    def step(self, action: ToolAction) -> StepResult:
        _ = self.task
        before_hash = self.state_hash()
        self._logical_time += 1
        self.last_fault_id = None

        validation = self._validate_action(action, before_hash)
        if validation is not None:
            return validation
        if action.tool_name == "calendar.create_event":
            return self._create_event_reliable(action, before_hash)
        if action.tool_name == "calendar.get_event":
            return self._get_event(action, before_hash)
        return self._send_invitations(action, before_hash)

    def _create_event_reliable(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        required = {"event_id", "title", "start_at", "organizer", "participants"}
        if set(arguments) != required or not isinstance(arguments.get("participants"), list):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_arguments",
            )
        scalar_keys = required - {"participants"}
        if not all(isinstance(arguments.get(key), str) for key in scalar_keys) or not all(
            isinstance(recipient, str) for recipient in arguments["participants"]
        ):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_arguments",
            )

        cached_value = {"created_event_id": arguments["event_id"]}
        next_state_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                """
                INSERT INTO calendar_events(
                    event_id, title, start_at, organizer, participants_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    arguments["event_id"],
                    arguments["title"],
                    arguments["start_at"],
                    arguments["organizer"],
                    json.dumps(arguments["participants"], sort_keys=True),
                ),
            )
            if action.idempotency_key is not None:
                self._connection.execute(
                    """
                    INSERT INTO idempotency_records(
                        idempotency_key, tool_name, request_digest, result_json,
                        committed_state_version
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        action.idempotency_key,
                        action.tool_name,
                        self._request_digest(action),
                        canonical_json(cached_value),
                        next_state_version,
                    ),
                )
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="duplicate_event",
            )
        self._state_version = next_state_version

        if self.r2_fault_mode == "event_postcommit_timeout_once":
            key = "calendar.create_event.postcommit"
            attempts = self._fault_attempts.get(key, 0) + 1
            self._fault_attempts[key] = attempts
            if attempts == 1:
                self.last_fault_id = "fault.workspace.event.postcommit_timeout_once"
                return self._result(
                    status="retryable_error",
                    before_hash=before_hash,
                    error_code="tool_timeout_postcommit",
                    retry_after_ms=10,
                )

        return self._result(status="ok", before_hash=before_hash, value=cached_value)

    def _get_event(self, action: ToolAction, before_hash: str) -> StepResult:
        if set(action.arguments) != {"event_id"} or not isinstance(
            action.arguments.get("event_id"), str
        ):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_arguments",
            )
        row = self._connection.execute(
            """
            SELECT event_id, title, start_at, organizer, participants_json
            FROM calendar_events
            WHERE event_id = ?
            """,
            (action.arguments["event_id"],),
        ).fetchone()
        if row is None:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="event_not_found",
            )
        event = dict(row)
        event["participants"] = json.loads(event.pop("participants_json"))
        return self._result(status="ok", before_hash=before_hash, value={"event": event})
