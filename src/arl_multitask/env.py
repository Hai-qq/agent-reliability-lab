"""Workspace v0.3 environment with a second task and idempotent writes."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any, Literal

from arl.core.types import Observation, SnapshotRef, StepResult, ToolAction, canonical_json
from arl.envs.workspace import SCHEMA_VERSION, WORKSPACE_TASK_ID, task_for_seed
from arl_r2.env import (
    ENV_VERSION as R2_ENV_VERSION,
)
from arl_r2.env import ReliableWorkspaceEnvironment

RESCHEDULE_TASK_ID = "workspace.reschedule_meeting_and_notify"
TASK_IDS = (WORKSPACE_TASK_ID, RESCHEDULE_TASK_ID)
ENV_VERSION = "workspace-v0.3.0"
FaultMode = Literal[
    "none",
    "event_postcommit_timeout_once",
    "reschedule_notifications_postcommit_timeout_once",
]

_WRITE_TOOLS = {
    "calendar.create_event",
    "calendar.update_event_time",
    "messages.send_invitations",
    "messages.send_reschedule_notifications",
    "workspace.resolve_change_request",
}
_READ_TOOLS = {
    "calendar.get_event",
    "messages.get_reschedule_notifications",
}


@dataclass(frozen=True)
class RescheduleTaskSpec:
    task_id: str
    seed: int
    event_id: str
    title: str
    start_at: str
    original_start_at: str
    organizer: str
    recipients: tuple[str, ...]
    request_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RescheduleTaskSpec:
        return cls(
            task_id=value["task_id"],
            seed=value["seed"],
            event_id=value["event_id"],
            title=value["title"],
            start_at=value["start_at"],
            original_start_at=value["original_start_at"],
            organizer=value["organizer"],
            recipients=tuple(value["recipients"]),
            request_id=value["request_id"],
        )


def reschedule_task_for_seed(seed: int) -> RescheduleTaskSpec:
    base = task_for_seed(seed)
    day = 20 + seed
    original_hour = 8 + (seed % 3)
    new_hour = original_hour + 2
    return RescheduleTaskSpec(
        task_id=RESCHEDULE_TASK_ID,
        seed=seed,
        event_id=f"synthetic-reschedule-event-{seed}",
        title=f"Reliability review {seed}",
        start_at=f"2026-09-{day:02d}T{new_hour:02d}:00:00Z",
        original_start_at=f"2026-09-{day:02d}T{original_hour:02d}:00:00Z",
        organizer="owner@synthetic.invalid",
        recipients=base.recipients,
        request_id=f"synthetic-change-request-{seed}",
    )


class MultiTaskWorkspaceEnvironment(ReliableWorkspaceEnvironment):
    """Preserve v0.1/v0.2 code while extending the synthetic state model."""

    def __init__(self, fault_mode: FaultMode = "none") -> None:
        if fault_mode not in {
            "none",
            "event_postcommit_timeout_once",
            "reschedule_notifications_postcommit_timeout_once",
        }:
            raise ValueError(f"Unknown fault mode: {fault_mode}")
        super().__init__(fault_mode="none")
        self.v03_fault_mode = fault_mode
        self._connection.executescript(
            """
            CREATE TABLE reschedule_notifications (
                event_id TEXT NOT NULL,
                recipient TEXT NOT NULL,
                kind TEXT NOT NULL,
                target_start_at TEXT NOT NULL,
                PRIMARY KEY (event_id, recipient, kind, target_start_at)
            );
            CREATE TABLE change_requests (
                request_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                requested_start_at TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE workspace_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

    def _clear_extension_tables(self) -> None:
        self._connection.execute("DELETE FROM reschedule_notifications")
        self._connection.execute("DELETE FROM change_requests")
        self._connection.execute("DELETE FROM workspace_metadata")

    def reset(self, task_id: str, seed: int) -> Observation:
        if task_id not in TASK_IDS:
            raise ValueError(f"Unknown task_id: {task_id}")
        self._clear_extension_tables()
        base_observation = super().reset(WORKSPACE_TASK_ID, seed)
        if task_id == WORKSPACE_TASK_ID:
            self._connection.execute(
                "INSERT INTO workspace_metadata(key, value) VALUES ('last_viewed_event_id', '')"
            )
            return Observation(
                task_id=task_id,
                seed=seed,
                env_version=ENV_VERSION,
                state_version=self._state_version,
                timestamp_logical=self._logical_time,
                state_hash=self.state_hash(),
                visible_task=base_observation.visible_task,
            )

        task = reschedule_task_for_seed(seed)
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                """
                INSERT INTO calendar_events(
                    event_id, title, start_at, organizer, participants_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task.event_id,
                    task.title,
                    task.original_start_at,
                    task.organizer,
                    json.dumps(list(task.recipients), sort_keys=True),
                ),
            )
            self._connection.execute(
                """
                INSERT INTO change_requests(
                    request_id, event_id, requested_start_at, status
                ) VALUES (?, ?, ?, 'pending')
                """,
                (task.request_id, task.event_id, task.start_at),
            )
            self._connection.execute(
                "INSERT INTO workspace_metadata(key, value) VALUES ('last_viewed_event_id', '')"
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        self._task = task
        self._state_version = 0
        self._logical_time = 0
        self._fault_attempts = {}
        self.last_fault_id = None
        return Observation(
            task_id=task_id,
            seed=seed,
            env_version=ENV_VERSION,
            state_version=0,
            timestamp_logical=0,
            state_hash=self.state_hash(),
            visible_task={
                "event_id": task.event_id,
                "title": task.title,
                "current_start_at": task.original_start_at,
                "new_start_at": task.start_at,
                "organizer": task.organizer,
                "recipients": list(task.recipients),
                "request_id": task.request_id,
            },
        )

    def _extension_rows(self, table: str, order_by: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            f"SELECT * FROM {table} ORDER BY {order_by}"  # noqa: S608 - fixed names
        ).fetchall()
        return [dict(row) for row in rows]

    def export_world(self) -> dict[str, Any]:
        world = super().export_world()
        world["env_version"] = ENV_VERSION
        world["reschedule_notifications"] = self._extension_rows(
            "reschedule_notifications",
            "event_id, recipient, kind, target_start_at",
        )
        world["change_requests"] = self._extension_rows("change_requests", "request_id")
        world["workspace_metadata"] = self._extension_rows("workspace_metadata", "key")
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
        notifications = world["reschedule_notifications"]
        requests = world["change_requests"]
        metadata = world["workspace_metadata"]
        r2_world = dict(world)
        for key in ("reschedule_notifications", "change_requests", "workspace_metadata"):
            r2_world.pop(key)
        r2_world["env_version"] = R2_ENV_VERSION
        self._clear_extension_tables()
        super().restore(
            SnapshotRef.from_value(
                {
                    "world": r2_world,
                    "runtime": payload["runtime"],
                }
            )
        )
        self._connection.execute("BEGIN")
        try:
            self._connection.executemany(
                """
                INSERT INTO reschedule_notifications(
                    event_id, recipient, kind, target_start_at
                ) VALUES (:event_id, :recipient, :kind, :target_start_at)
                """,
                notifications,
            )
            self._connection.executemany(
                """
                INSERT INTO change_requests(
                    request_id, event_id, requested_start_at, status
                ) VALUES (:request_id, :event_id, :requested_start_at, :status)
                """,
                requests,
            )
            self._connection.executemany(
                "INSERT INTO workspace_metadata(key, value) VALUES (:key, :value)",
                metadata,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        if world["task_id"] == RESCHEDULE_TASK_ID:
            self._task = RescheduleTaskSpec.from_dict(world["task"])

    def _validate_action(self, action: ToolAction, before_hash: str) -> StepResult | None:
        if action.schema_version != SCHEMA_VERSION:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="schema_version_unsupported",
            )
        if action.tool_name not in _WRITE_TOOLS | _READ_TOOLS:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="unknown_tool",
            )
        if action.tool_name in _WRITE_TOOLS:
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

    def _insert_idempotency_record(
        self,
        action: ToolAction,
        value: dict[str, Any],
        next_state_version: int,
    ) -> None:
        if action.idempotency_key is None:
            return
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
                canonical_json(value),
                next_state_version,
            ),
        )

    def _postcommit_fault(self, tool_name: str, before_hash: str) -> StepResult | None:
        expected_mode = {
            "calendar.create_event": "event_postcommit_timeout_once",
            "messages.send_reschedule_notifications": (
                "reschedule_notifications_postcommit_timeout_once"
            ),
        }.get(tool_name)
        if self.v03_fault_mode != expected_mode:
            return None
        attempts = self._fault_attempts.get(tool_name, 0) + 1
        self._fault_attempts[tool_name] = attempts
        if attempts != 1:
            return None
        fault_ids = {
            "calendar.create_event": "fault.workspace.event.postcommit_timeout_once",
            "messages.send_reschedule_notifications": (
                "fault.workspace.reschedule_notifications.postcommit_timeout_once"
            ),
        }
        self.last_fault_id = fault_ids[tool_name]
        return self._result(
            status="retryable_error",
            before_hash=before_hash,
            error_code="tool_timeout_postcommit",
            retry_after_ms=10,
        )

    def step(self, action: ToolAction) -> StepResult:
        _ = self.task
        before_hash = self.state_hash()
        self._logical_time += 1
        self.last_fault_id = None
        validation = self._validate_action(action, before_hash)
        if validation is not None:
            return validation

        if action.tool_name == "calendar.create_event":
            result = self._create_event_reliable(action, before_hash)
            if result.ok:
                return self._postcommit_fault(action.tool_name, before_hash) or result
            return result
        if action.tool_name == "calendar.get_event":
            return self._get_event(action, before_hash)
        if action.tool_name == "calendar.update_event_time":
            return self._update_event_time(action, before_hash)
        if action.tool_name == "messages.send_invitations":
            return self._send_invitations_idempotent(action, before_hash)
        if action.tool_name == "messages.send_reschedule_notifications":
            return self._send_reschedule_notifications(action, before_hash)
        if action.tool_name == "messages.get_reschedule_notifications":
            return self._get_reschedule_notifications(action, before_hash)
        return self._resolve_change_request(action, before_hash)

    def _send_invitations_idempotent(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        if set(arguments) != {"event_id", "recipients"} or not isinstance(
            arguments.get("event_id"), str
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        recipients = arguments.get("recipients")
        if (
            not isinstance(recipients, list)
            or not recipients
            or not all(isinstance(recipient, str) for recipient in recipients)
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        event = self._connection.execute(
            "SELECT 1 FROM calendar_events WHERE event_id = ?", (arguments["event_id"],)
        ).fetchone()
        if event is None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="event_not_found"
            )
        known = {row["email"] for row in self._connection.execute("SELECT email FROM contacts")}
        if any(recipient not in known for recipient in recipients):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="unknown_recipient"
            )
        value = {"invitation_count": len(recipients)}
        next_state_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            for recipient in recipients:
                self._connection.execute(
                    """
                    INSERT INTO invitations(event_id, recipient, status)
                    VALUES (?, ?, 'sent')
                    """,
                    (arguments["event_id"], recipient),
                )
            self._insert_idempotency_record(action, value, next_state_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="duplicate_invitation",
            )
        self._state_version = next_state_version
        return self._result(status="ok", before_hash=before_hash, value=value)

    def _update_event_time(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        if set(arguments) != {"event_id", "new_start_at"} or not all(
            isinstance(arguments.get(key), str) for key in ("event_id", "new_start_at")
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        row = self._connection.execute(
            "SELECT start_at FROM calendar_events WHERE event_id = ?",
            (arguments["event_id"],),
        ).fetchone()
        if row is None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="event_not_found"
            )
        if row["start_at"] == arguments["new_start_at"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="event_time_unchanged"
            )
        value = {
            "updated_event_id": arguments["event_id"],
            "new_start_at": arguments["new_start_at"],
        }
        next_state_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                "UPDATE calendar_events SET start_at = ? WHERE event_id = ?",
                (arguments["new_start_at"], arguments["event_id"]),
            )
            self._insert_idempotency_record(action, value, next_state_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="idempotency_key_reused",
            )
        self._state_version = next_state_version
        return self._result(status="ok", before_hash=before_hash, value=value)

    def _send_reschedule_notifications(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        required = {"event_id", "recipients", "target_start_at"}
        if set(arguments) != required or not all(
            isinstance(arguments.get(key), str) for key in ("event_id", "target_start_at")
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        recipients = arguments.get("recipients")
        if (
            not isinstance(recipients, list)
            or not recipients
            or not all(isinstance(recipient, str) for recipient in recipients)
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        event = self._connection.execute(
            "SELECT start_at, participants_json FROM calendar_events WHERE event_id = ?",
            (arguments["event_id"],),
        ).fetchone()
        if event is None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="event_not_found"
            )
        if event["start_at"] != arguments["target_start_at"]:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="event_time_not_updated",
            )
        participants = set(json.loads(event["participants_json"]))
        if any(recipient not in participants for recipient in recipients):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="recipient_not_participant",
            )
        value = {"notification_count": len(recipients)}
        next_state_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            for recipient in recipients:
                self._connection.execute(
                    """
                    INSERT INTO reschedule_notifications(
                        event_id, recipient, kind, target_start_at
                    ) VALUES (?, ?, 'reschedule', ?)
                    """,
                    (arguments["event_id"], recipient, arguments["target_start_at"]),
                )
            self._insert_idempotency_record(action, value, next_state_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="duplicate_reschedule_notification",
            )
        self._state_version = next_state_version
        return self._postcommit_fault(action.tool_name, before_hash) or self._result(
            status="ok", before_hash=before_hash, value=value
        )

    def _get_reschedule_notifications(self, action: ToolAction, before_hash: str) -> StepResult:
        if set(action.arguments) != {"event_id"} or not isinstance(
            action.arguments.get("event_id"), str
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        notifications = [
            dict(row)
            for row in self._connection.execute(
                """
                SELECT event_id, recipient, kind, target_start_at
                FROM reschedule_notifications
                WHERE event_id = ?
                ORDER BY recipient, kind, target_start_at
                """,
                (action.arguments["event_id"],),
            ).fetchall()
        ]
        return self._result(
            status="ok",
            before_hash=before_hash,
            value={"notifications": notifications},
        )

    def _resolve_change_request(self, action: ToolAction, before_hash: str) -> StepResult:
        if set(action.arguments) != {"request_id"} or not isinstance(
            action.arguments.get("request_id"), str
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        request = self._connection.execute(
            """
            SELECT request_id, event_id, requested_start_at, status
            FROM change_requests WHERE request_id = ?
            """,
            (action.arguments["request_id"],),
        ).fetchone()
        if request is None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="request_not_found"
            )
        if request["status"] != "pending":
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="request_already_resolved",
            )
        expected_recipients = set(self.task.recipients)
        notified = {
            row["recipient"]
            for row in self._connection.execute(
                """
                SELECT recipient FROM reschedule_notifications
                WHERE event_id = ? AND kind = 'reschedule' AND target_start_at = ?
                """,
                (request["event_id"], request["requested_start_at"]),
            )
        }
        if notified != expected_recipients:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="notifications_incomplete",
            )
        value = {"resolved_request_id": request["request_id"]}
        next_state_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                "UPDATE change_requests SET status = 'resolved' WHERE request_id = ?",
                (request["request_id"],),
            )
            self._insert_idempotency_record(action, value, next_state_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="idempotency_key_reused",
            )
        self._state_version = next_state_version
        return self._result(status="ok", before_hash=before_hash, value=value)
