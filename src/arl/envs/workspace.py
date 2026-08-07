"""Deterministic, SQLite-backed synthetic Workspace environment."""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from arl.core.types import Observation, SnapshotRef, StepResult, ToolAction, digest_value

WORKSPACE_TASK_ID = "workspace.schedule_meeting_and_notify"
ENV_VERSION = "workspace-v0.1.0"
SCHEMA_VERSION = "1.0"
FaultMode = Literal["none", "invites_precommit_timeout_once"]

_CONTACTS = (
    ("alex", "Alex Synthetic", "alex@synthetic.invalid"),
    ("blair", "Blair Synthetic", "blair@synthetic.invalid"),
    ("casey", "Casey Synthetic", "casey@synthetic.invalid"),
    ("devon", "Devon Synthetic", "devon@synthetic.invalid"),
)


@dataclass(frozen=True)
class WorkspaceTaskSpec:
    """Public task goal plus evaluator-owned expected values."""

    task_id: str
    seed: int
    event_id: str
    title: str
    start_at: str
    organizer: str
    recipients: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def task_for_seed(seed: int) -> WorkspaceTaskSpec:
    if seed < 0:
        raise ValueError("seed must be non-negative")
    rng = random.Random(seed)
    recipients = tuple(sorted(contact[2] for contact in rng.sample(_CONTACTS, 2)))
    day = 10 + seed
    hour = 9 + (seed % 4)
    return WorkspaceTaskSpec(
        task_id=WORKSPACE_TASK_ID,
        seed=seed,
        event_id=f"synthetic-event-{seed}",
        title=f"Reliability sync {seed}",
        start_at=f"2026-09-{day:02d}T{hour:02d}:00:00Z",
        organizer="owner@synthetic.invalid",
        recipients=recipients,
    )


class WorkspaceEnvironment:
    """A resettable synthetic calendar/messages world with typed failures."""

    def __init__(self, fault_mode: FaultMode = "none") -> None:
        if fault_mode not in {"none", "invites_precommit_timeout_once"}:
            raise ValueError(f"Unknown fault mode: {fault_mode}")
        self.fault_mode = fault_mode
        self.last_fault_id: str | None = None
        self._connection = sqlite3.connect(":memory:", isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()
        self._task: WorkspaceTaskSpec | None = None
        self._state_version = 0
        self._logical_time = 0
        self._fault_attempts: dict[str, int] = {}

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE contacts (
                contact_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            );
            CREATE TABLE calendar_events (
                event_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                start_at TEXT NOT NULL,
                organizer TEXT NOT NULL,
                participants_json TEXT NOT NULL
            );
            CREATE TABLE invitations (
                event_id TEXT NOT NULL,
                recipient TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (event_id, recipient),
                FOREIGN KEY (event_id) REFERENCES calendar_events(event_id)
            );
            """
        )

    @property
    def task(self) -> WorkspaceTaskSpec:
        if self._task is None:
            raise RuntimeError("Environment must be reset before use")
        return self._task

    @property
    def state_version(self) -> int:
        return self._state_version

    @property
    def logical_time(self) -> int:
        return self._logical_time

    def close(self) -> None:
        self._connection.close()

    def reset(self, task_id: str, seed: int) -> Observation:
        if task_id != WORKSPACE_TASK_ID:
            raise ValueError(f"Unknown task_id: {task_id}")
        self._connection.execute("BEGIN")
        try:
            self._connection.execute("DELETE FROM invitations")
            self._connection.execute("DELETE FROM calendar_events")
            self._connection.execute("DELETE FROM contacts")
            self._connection.executemany(
                "INSERT INTO contacts(contact_id, name, email) VALUES (?, ?, ?)",
                _CONTACTS,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        self._task = task_for_seed(seed)
        self._state_version = 0
        self._logical_time = 0
        self._fault_attempts = {}
        self.last_fault_id = None
        return Observation(
            task_id=task_id,
            seed=seed,
            env_version=ENV_VERSION,
            state_version=self._state_version,
            timestamp_logical=self._logical_time,
            state_hash=self.state_hash(),
            visible_task={
                "event_id": self.task.event_id,
                "title": self.task.title,
                "start_at": self.task.start_at,
                "organizer": self.task.organizer,
                "recipients": list(self.task.recipients),
            },
        )

    def _rows(self, table: str, order_by: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            f"SELECT * FROM {table} ORDER BY {order_by}"  # noqa: S608 - fixed internal names
        ).fetchall()
        values = [dict(row) for row in rows]
        if table == "calendar_events":
            for value in values:
                value["participants"] = json.loads(value.pop("participants_json"))
        return values

    def export_world(self) -> dict[str, Any]:
        return {
            "env_version": ENV_VERSION,
            "task_id": self.task.task_id,
            "seed": self.task.seed,
            "task": self.task.as_dict(),
            "state_version": self._state_version,
            "contacts": self._rows("contacts", "contact_id"),
            "calendar_events": self._rows("calendar_events", "event_id"),
            "invitations": self._rows("invitations", "event_id, recipient"),
        }

    def state_hash(self) -> str:
        return digest_value(self.export_world())

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
        runtime = payload["runtime"]
        if world["env_version"] != ENV_VERSION:
            raise ValueError("Snapshot environment version mismatch")
        self._connection.execute("BEGIN")
        try:
            self._connection.execute("DELETE FROM invitations")
            self._connection.execute("DELETE FROM calendar_events")
            self._connection.execute("DELETE FROM contacts")
            self._connection.executemany(
                "INSERT INTO contacts(contact_id, name, email) VALUES (:contact_id, :name, :email)",
                world["contacts"],
            )
            self._connection.executemany(
                """
                INSERT INTO calendar_events(
                    event_id, title, start_at, organizer, participants_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        event["event_id"],
                        event["title"],
                        event["start_at"],
                        event["organizer"],
                        json.dumps(event["participants"], sort_keys=True),
                    )
                    for event in world["calendar_events"]
                ],
            )
            self._connection.executemany(
                """
                INSERT INTO invitations(event_id, recipient, status)
                VALUES (:event_id, :recipient, :status)
                """,
                world["invitations"],
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        task = world["task"]
        self._task = WorkspaceTaskSpec(
            task_id=task["task_id"],
            seed=task["seed"],
            event_id=task["event_id"],
            title=task["title"],
            start_at=task["start_at"],
            organizer=task["organizer"],
            recipients=tuple(task["recipients"]),
        )
        self._state_version = world["state_version"]
        self._logical_time = runtime["logical_time"]
        self._fault_attempts = dict(runtime["fault_attempts"])
        self.last_fault_id = None

    def _result(
        self,
        *,
        status: Literal["ok", "retryable_error", "fatal_error", "conflict"],
        before_hash: str,
        value: dict[str, Any] | None = None,
        error_code: str | None = None,
        retry_after_ms: int | None = None,
    ) -> StepResult:
        return StepResult(
            status=status,
            value=value,
            error_code=error_code,
            state_version=self._state_version,
            retry_after_ms=retry_after_ms,
            state_hash_before=before_hash,
            state_hash_after=self.state_hash(),
            timestamp_logical=self._logical_time,
        )

    def _validate_common(self, action: ToolAction, before_hash: str) -> StepResult | None:
        if action.schema_version != SCHEMA_VERSION:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="schema_version_unsupported",
            )
        if (
            action.expected_state_version is not None
            and action.expected_state_version != self._state_version
        ):
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="state_version_conflict",
            )
        if action.tool_name not in {"calendar.create_event", "messages.send_invitations"}:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="unknown_tool",
            )
        return None

    def _inject_fault(self, action: ToolAction, before_hash: str) -> StepResult | None:
        if (
            self.fault_mode == "invites_precommit_timeout_once"
            and action.tool_name == "messages.send_invitations"
        ):
            key = "messages.send_invitations"
            attempts = self._fault_attempts.get(key, 0) + 1
            self._fault_attempts[key] = attempts
            if attempts == 1:
                self.last_fault_id = "fault.workspace.invites.precommit_timeout_once"
                return self._result(
                    status="retryable_error",
                    before_hash=before_hash,
                    error_code="tool_timeout_precommit",
                    retry_after_ms=10,
                )
        return None

    def step(self, action: ToolAction) -> StepResult:
        _ = self.task
        before_hash = self.state_hash()
        self._logical_time += 1
        self.last_fault_id = None

        common_error = self._validate_common(action, before_hash)
        if common_error is not None:
            return common_error
        fault = self._inject_fault(action, before_hash)
        if fault is not None:
            return fault

        if action.tool_name == "calendar.create_event":
            return self._create_event(action, before_hash)
        return self._send_invitations(action, before_hash)

    def _create_event(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        required = {"event_id", "title", "start_at", "organizer", "participants"}
        if set(arguments) != required or not isinstance(arguments["participants"], list):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_arguments",
            )
        scalar_keys = required - {"participants"}
        if not all(isinstance(arguments[key], str) for key in scalar_keys) or not all(
            isinstance(recipient, str) for recipient in arguments["participants"]
        ):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_arguments",
            )
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
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="duplicate_event",
            )
        self._state_version += 1
        return self._result(
            status="ok",
            before_hash=before_hash,
            value={"created_event_id": arguments["event_id"]},
        )

    def _send_invitations(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        if set(arguments) != {"event_id", "recipients"} or not isinstance(
            arguments["event_id"], str
        ):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_arguments",
            )
        recipients = arguments["recipients"]
        if (
            not isinstance(recipients, list)
            or not recipients
            or not all(isinstance(recipient, str) for recipient in recipients)
        ):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_arguments",
            )
        event_exists = self._connection.execute(
            "SELECT 1 FROM calendar_events WHERE event_id = ?",
            (arguments["event_id"],),
        ).fetchone()
        if event_exists is None:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="event_not_found",
            )
        known_recipients = {
            row["email"] for row in self._connection.execute("SELECT email FROM contacts")
        }
        if any(recipient not in known_recipients for recipient in recipients):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="unknown_recipient",
            )

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
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="duplicate_invitation",
            )
        self._state_version += 1
        return self._result(
            status="ok",
            before_hash=before_hash,
            value={"invitation_count": len(recipients)},
        )

    def sqlite_file(self) -> Path | None:
        """Return no path: this first increment intentionally stays in memory."""
        return None
