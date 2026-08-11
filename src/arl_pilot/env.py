"""Deterministic SQLite product world for ARL task-spec packs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import Any

from arl.core.types import (
    Observation,
    SnapshotRef,
    StepResult,
    ToolAction,
    canonical_json,
    digest_value,
)
from arl_pilot.specs import (
    CANONICAL_SCHEMA_VERSION,
    CONDITIONS,
    DRIFT_SCHEMA_VERSION,
    ENV_VERSION,
    OperationSpec,
    PilotTaskSpec,
)


class PilotEnvironment:
    """Execute one frozen task spec without exposing fault state to the policy."""

    def __init__(self, spec: PilotTaskSpec, condition: str) -> None:
        if condition not in CONDITIONS:
            raise ValueError(f"Unknown condition: {condition}")
        self.spec = spec
        self.condition = condition
        self._db = sqlite3.connect(":memory:")
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE kv_state (
                path TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            CREATE TABLE operation_counts (
                operation_id TEXT PRIMARY KEY,
                count INTEGER NOT NULL
            );
            CREATE TABLE idempotency_records (
                idempotency_key TEXT PRIMARY KEY,
                request_sha256 TEXT NOT NULL,
                result_json TEXT NOT NULL
            );
            """
        )
        self.state_version = 0
        self.logical_time = 0
        self.last_fault_id: str | None = None
        self._fault_triggered = False
        self._task_id: str | None = None
        self._seed: int | None = None

    @property
    def fault_enabled(self) -> bool:
        return self.condition == "recoverable_fault"

    def close(self) -> None:
        self._db.close()

    def _replace_world(self, values: dict[str, Any]) -> None:
        with self._db:
            self._db.execute("DELETE FROM kv_state")
            self._db.execute("DELETE FROM operation_counts")
            self._db.execute("DELETE FROM idempotency_records")
            self._db.executemany(
                "INSERT INTO kv_state(path, value_json) VALUES (?, ?)",
                [(path, canonical_json(value)) for path, value in sorted(values.items())],
            )

    def reset(self, task_id: str, seed: int) -> Observation:
        if task_id != self.spec.task_id:
            raise ValueError(f"Environment is bound to {self.spec.task_id}, not {task_id}")
        if seed < 0:
            raise ValueError("Seed must be non-negative")
        self._replace_world(self.spec.initial_values_dict)
        self.state_version = 0
        self.logical_time = 0
        self.last_fault_id = None
        self._fault_triggered = False
        self._task_id = task_id
        self._seed = seed
        return Observation(
            task_id=task_id,
            seed=seed,
            env_version=ENV_VERSION,
            state_version=self.state_version,
            timestamp_logical=self.logical_time,
            state_hash=self.state_hash(),
            visible_task=self.spec.visible_task,
        )

    def _require_reset(self) -> None:
        if self._task_id is None or self._seed is None:
            raise RuntimeError("PilotEnvironment must be reset before use")

    def _values(self) -> dict[str, Any]:
        return {
            row["path"]: json.loads(row["value_json"])
            for row in self._db.execute("SELECT path, value_json FROM kv_state ORDER BY path")
        }

    def _operation_counts(self) -> dict[str, int]:
        return {
            row["operation_id"]: int(row["count"])
            for row in self._db.execute(
                "SELECT operation_id, count FROM operation_counts ORDER BY operation_id"
            )
        }

    def _idempotency_records(self) -> list[dict[str, str]]:
        return [
            {
                "idempotency_key": row["idempotency_key"],
                "request_sha256": row["request_sha256"],
                "result_sha256": digest_value(json.loads(row["result_json"])),
            }
            for row in self._db.execute(
                """SELECT idempotency_key, request_sha256, result_json
                   FROM idempotency_records ORDER BY idempotency_key"""
            )
        ]

    def snapshot(self) -> SnapshotRef:
        self._require_reset()
        return SnapshotRef.from_value(
            {
                "env_version": ENV_VERSION,
                "task_id": self._task_id,
                "seed": self._seed,
                "values": self._values(),
                "operation_counts": self._operation_counts(),
                "idempotency_records": self._idempotency_records(),
                "state_version": self.state_version,
                "logical_time": self.logical_time,
            }
        )

    def state_hash(self) -> str:
        return self.snapshot().sha256

    def business_values(self) -> dict[str, Any]:
        self._require_reset()
        return self._values()

    def public_descriptor(self, semantic_action: ToolAction) -> dict[str, Any]:
        operation = self._operation_for_semantic_action(semantic_action)
        action_schema = CANONICAL_SCHEMA_VERSION
        action_fields = tuple(operation.arguments)
        result_schema = CANONICAL_SCHEMA_VERSION
        result_fields = operation.required_result_fields
        if (
            self.fault_enabled
            and self.spec.fault_family == "input_schema_drift"
            and operation.operation_id == self.spec.fault_operation_id
        ):
            action_schema = DRIFT_SCHEMA_VERSION
            action_fields = tuple(self.spec.drifted_arguments(operation))
        if (
            self.fault_enabled
            and self.spec.fault_family == "output_schema_drift"
            and operation.operation_id == self.spec.fault_operation_id
        ):
            result_schema = DRIFT_SCHEMA_VERSION
            result_fields = tuple(dict(self.spec.output_drift_result))
        return {
            "tool_name": operation.tool_name,
            "action": {
                "schema_version": action_schema,
                "required_fields": list(action_fields),
                "additional_fields": False,
            },
            "result": {
                "schema_version": result_schema,
                "required_fields": list(result_fields),
                "additional_fields": False,
            },
        }

    def adapt_input_action(self, semantic_action: ToolAction) -> ToolAction:
        operation = self._operation_for_semantic_action(semantic_action)
        descriptor = self.public_descriptor(semantic_action)
        advertised = descriptor["action"]
        if advertised["schema_version"] == CANONICAL_SCHEMA_VERSION:
            return semantic_action
        drifted_arguments = self.spec.drifted_arguments(operation)
        expected_descriptor = {
            "schema_version": DRIFT_SCHEMA_VERSION,
            "required_fields": list(drifted_arguments),
            "additional_fields": False,
        }
        if (
            semantic_action.schema_version != CANONICAL_SCHEMA_VERSION
            or semantic_action.arguments != operation.arguments
            or advertised != expected_descriptor
        ):
            raise ValueError("No exact input-schema adapter is registered")
        return replace(
            semantic_action,
            schema_version=DRIFT_SCHEMA_VERSION,
            arguments=drifted_arguments,
        )

    def normalize_result(self, semantic_action: ToolAction, result: StepResult) -> StepResult:
        operation = self._operation_for_semantic_action(semantic_action)
        descriptor = self.public_descriptor(semantic_action)
        advertised = descriptor["result"]
        if advertised["schema_version"] == CANONICAL_SCHEMA_VERSION:
            return result
        drifted_result = dict(self.spec.output_drift_result)
        expected_descriptor = {
            "schema_version": DRIFT_SCHEMA_VERSION,
            "required_fields": list(drifted_result),
            "additional_fields": False,
        }
        value = result.value
        if (
            not result.ok
            or value is None
            or advertised != expected_descriptor
            or value != drifted_result
        ):
            raise ValueError("No exact output-schema normalizer is registered")
        return replace(result, value=dict(operation.result_value))

    def result_contract_valid(self, semantic_action: ToolAction, result: StepResult) -> bool:
        if not result.ok or result.value is None:
            return False
        if semantic_action.tool_name == f"{self.spec.domain}.read_state":
            return set(result.value) == {"values"} and isinstance(result.value["values"], dict)
        operation = self._operation_for_semantic_action(semantic_action)
        return set(result.value) == set(operation.result_value) and all(
            field in result.value for field in operation.required_result_fields
        )

    def confirmation_action(self, semantic_action: ToolAction) -> ToolAction | None:
        operation = self._operation_for_semantic_action(semantic_action)
        if not operation.effects:
            return None
        paths = sorted(path for path, _ in operation.effects)
        if not set(paths).issubset(self.spec.public_read_paths):
            return None
        return self._public_read_action(paths)

    def confirmation_matches(self, semantic_action: ToolAction, result: StepResult) -> bool:
        operation = self._operation_for_semantic_action(semantic_action)
        if not result.ok or result.value is None:
            return False
        values = result.value.get("values")
        return isinstance(values, dict) and all(
            values.get(path) == expected for path, expected in operation.effects
        )

    def conflict_probe_action(self) -> ToolAction | None:
        if not self.spec.conflict_guard:
            return None
        return self._public_read_action(sorted(path for path, _ in self.spec.conflict_guard))

    def conflict_guard_matches(self, result: StepResult) -> bool:
        if not result.ok or result.value is None:
            return False
        values = result.value.get("values")
        return isinstance(values, dict) and all(
            values.get(path) == expected for path, expected in self.spec.conflict_guard
        )

    def compensation_actions(self, semantic_action: ToolAction) -> tuple[ToolAction, ...]:
        operation = self._operation_for_semantic_action(semantic_action)
        if operation.operation_id != self.spec.fault_operation_id:
            return ()
        return tuple(item.semantic_action() for item in self.spec.compensation_operations)

    def is_write(self, semantic_action: ToolAction) -> bool:
        return self._operation_for_semantic_action(semantic_action).is_write

    def _public_read_action(self, paths: list[str]) -> ToolAction:
        return ToolAction(
            tool_name=f"{self.spec.domain}.read_state",
            schema_version=CANONICAL_SCHEMA_VERSION,
            arguments={"paths": paths},
            expected_state_version=self.state_version,
        )

    def _operation_for_semantic_action(self, action: ToolAction) -> OperationSpec:
        candidates = [
            item for item in self.spec.all_operations if item.tool_name == action.tool_name
        ]
        for operation in candidates:
            if action.arguments == operation.arguments:
                return operation
            if (
                operation.operation_id == self.spec.fault_operation_id
                and self.spec.fault_family == "input_schema_drift"
                and action.arguments == self.spec.drifted_arguments(operation)
            ):
                return operation
        raise ValueError(f"Unknown operation for {action.tool_name} with supplied arguments")

    def _request_sha256(self, action: ToolAction) -> str:
        return digest_value(
            {
                "tool_name": action.tool_name,
                "schema_version": action.schema_version,
                "arguments": action.arguments,
            }
        )

    def _result(
        self,
        *,
        status: str,
        value: dict[str, Any] | None,
        error_code: str | None,
        state_hash_before: str,
        retry_after_ms: int | None = None,
    ) -> StepResult:
        return StepResult(
            status=status,  # type: ignore[arg-type]
            value=value,
            error_code=error_code,
            state_version=self.state_version,
            retry_after_ms=retry_after_ms,
            state_hash_before=state_hash_before,
            state_hash_after=self.state_hash(),
            timestamp_logical=self.logical_time,
        )

    def _rejection(
        self,
        state_hash_before: str,
        error_code: str,
        *,
        status: str = "fatal_error",
    ) -> StepResult:
        return self._result(
            status=status,
            value=None,
            error_code=error_code,
            state_hash_before=state_hash_before,
        )

    def _apply_operation(self, operation: OperationSpec, action: ToolAction) -> None:
        request_sha256 = self._request_sha256(action)
        with self._db:
            for path, value in operation.effects:
                updated = self._db.execute(
                    "UPDATE kv_state SET value_json = ? WHERE path = ?",
                    (canonical_json(value), path),
                )
                if updated.rowcount != 1:
                    raise RuntimeError(f"Operation effect references unknown path: {path}")
            self._db.execute(
                """INSERT INTO operation_counts(operation_id, count) VALUES (?, 1)
                   ON CONFLICT(operation_id) DO UPDATE SET count = count + 1""",
                (operation.operation_id,),
            )
            if action.idempotency_key is not None:
                self._db.execute(
                    """INSERT INTO idempotency_records(
                           idempotency_key, request_sha256, result_json
                       ) VALUES (?, ?, ?)""",
                    (
                        action.idempotency_key,
                        request_sha256,
                        canonical_json(operation.result_value),
                    ),
                )
        self.state_version += 1

    def _idempotent_replay(self, action: ToolAction, state_hash_before: str) -> StepResult | None:
        if action.idempotency_key is None:
            return None
        row = self._db.execute(
            """SELECT request_sha256, result_json FROM idempotency_records
               WHERE idempotency_key = ?""",
            (action.idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != self._request_sha256(action):
            return self._rejection(state_hash_before, "idempotency_key_conflict")
        return self._result(
            status="ok",
            value=json.loads(row["result_json"]),
            error_code=None,
            state_hash_before=state_hash_before,
        )

    def _step_public_read(self, action: ToolAction, state_hash_before: str) -> StepResult:
        if action.schema_version != CANONICAL_SCHEMA_VERSION:
            return self._rejection(state_hash_before, "schema_version_unsupported")
        if set(action.arguments) != {"paths"} or not isinstance(action.arguments["paths"], list):
            return self._rejection(state_hash_before, "invalid_arguments")
        paths = action.arguments["paths"]
        if not paths or not all(isinstance(path, str) for path in paths):
            return self._rejection(state_hash_before, "invalid_arguments")
        if not set(paths).issubset(self.spec.public_read_paths):
            return self._rejection(state_hash_before, "public_read_scope_violation")
        values = self._values()
        return self._result(
            status="ok",
            value={"values": {path: values[path] for path in paths}},
            error_code=None,
            state_hash_before=state_hash_before,
        )

    def step(self, action: ToolAction) -> StepResult:
        self._require_reset()
        state_hash_before = self.state_hash()
        self.logical_time += 1
        self.last_fault_id = None

        if action.tool_name == f"{self.spec.domain}.read_state":
            if (
                action.expected_state_version is not None
                and action.expected_state_version != self.state_version
            ):
                return self._rejection(
                    state_hash_before,
                    "state_version_conflict",
                    status="conflict",
                )
            return self._step_public_read(action, state_hash_before)

        try:
            operation = self._operation_for_semantic_action(action)
        except ValueError:
            return self._rejection(state_hash_before, "unknown_tool_or_arguments")

        replay = self._idempotent_replay(action, state_hash_before)
        if replay is not None:
            return replay

        if (
            action.expected_state_version is not None
            and action.expected_state_version != self.state_version
        ):
            return self._rejection(
                state_hash_before,
                "state_version_conflict",
                status="conflict",
            )

        expected_schema = CANONICAL_SCHEMA_VERSION
        expected_arguments = operation.arguments
        is_fault_target = operation.operation_id == self.spec.fault_operation_id
        if (
            self.fault_enabled
            and is_fault_target
            and self.spec.fault_family == "input_schema_drift"
        ):
            self.last_fault_id = self.spec.fault_id
            expected_schema = DRIFT_SCHEMA_VERSION
            expected_arguments = self.spec.drifted_arguments(operation)
        if action.schema_version != expected_schema or action.arguments != expected_arguments:
            return self._rejection(state_hash_before, "schema_version_unsupported")

        if self.fault_enabled and is_fault_target:
            family = self.spec.fault_family
            if family == "postcommit_response_loss" and not self._fault_triggered:
                self._fault_triggered = True
                self.last_fault_id = self.spec.fault_id
                self._apply_operation(operation, action)
                return self._result(
                    status="retryable_error",
                    value=None,
                    error_code="tool_timeout_postcommit",
                    state_hash_before=state_hash_before,
                    retry_after_ms=10,
                )
            if family == "retryable_invocation_error" and not self._fault_triggered:
                self._fault_triggered = True
                self.last_fault_id = self.spec.fault_id
                return self._result(
                    status="retryable_error",
                    value=None,
                    error_code="tool_temporarily_unavailable",
                    state_hash_before=state_hash_before,
                    retry_after_ms=10,
                )
            if family == "compatible_state_conflict" and not self._fault_triggered:
                self._fault_triggered = True
                self.last_fault_id = self.spec.fault_id
                with self._db:
                    for path, value in self.spec.conflict_effects:
                        updated = self._db.execute(
                            "UPDATE kv_state SET value_json = ? WHERE path = ?",
                            (canonical_json(value), path),
                        )
                        if updated.rowcount != 1:
                            raise RuntimeError(f"Conflict effect references unknown path: {path}")
                self.state_version += 1
                return self._rejection(
                    state_hash_before,
                    "state_version_conflict",
                    status="conflict",
                )
            if family == "bounded_compensation" and not self._fault_triggered:
                self._fault_triggered = True
                self.last_fault_id = self.spec.fault_id
                return self._rejection(state_hash_before, "preferred_option_unavailable")
            if family in {"input_schema_drift", "output_schema_drift"}:
                self.last_fault_id = self.spec.fault_id

        if operation.is_write:
            self._apply_operation(operation, action)
        value = dict(operation.result_value)
        if (
            self.fault_enabled
            and is_fault_target
            and self.spec.fault_family == "output_schema_drift"
        ):
            value = dict(self.spec.output_drift_result)
        return self._result(
            status="ok",
            value=value,
            error_code=None,
            state_hash_before=state_hash_before,
        )
