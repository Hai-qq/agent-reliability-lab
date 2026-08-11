"""Migration adapters for the first cross-domain main-study smoke tasks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from arl.core.types import EvaluationReport, Observation, SnapshotRef, StepResult, ToolAction
from arl.envs.workspace import WORKSPACE_TASK_ID
from arl_mainstudy.catalog import BLUEPRINTS_BY_TASK_ID, TaskBlueprint
from arl_mainstudy.protocol import RuntimeEnvironment
from arl_multitask.env import MultiTaskWorkspaceEnvironment
from arl_multitask.evaluator import evaluate_workspace_multitask
from arl_multitask.experiment import task_actions as workspace_task_actions
from arl_multitask.runtime import MultiTaskRuntime
from arl_retail.env import PURCHASE_TASK_ID, RetailEnvironment
from arl_retail.evaluator import evaluate_retail
from arl_retail.experiment import task_actions as retail_task_actions
from arl_retail.runtime import RetailRuntime

SMOKE_TEMPLATE_IDS = (
    BLUEPRINTS_BY_TASK_ID[WORKSPACE_TASK_ID].template_id,
    BLUEPRINTS_BY_TASK_ID[PURCHASE_TASK_ID].template_id,
)


def _semantic(actions: Sequence[ToolAction]) -> tuple[ToolAction, ...]:
    return tuple(
        replace(action, idempotency_key=None, expected_state_version=None) for action in actions
    )


class WorkspaceRuntimeHooks:
    domain = "workspace"
    _write_tools = {
        "calendar.create_event",
        "calendar.update_event_time",
        "messages.send_invitations",
        "messages.send_reschedule_notifications",
        "workspace.resolve_change_request",
    }

    def is_write(self, action: ToolAction) -> bool:
        return action.tool_name in self._write_tools

    def result_contract_valid(
        self,
        environment: RuntimeEnvironment,
        action: ToolAction,
        result: StepResult,
    ) -> bool:
        if not isinstance(environment, MultiTaskWorkspaceEnvironment):
            raise TypeError("Workspace hooks require MultiTaskWorkspaceEnvironment")
        return MultiTaskRuntime._result_contract_valid(environment, action, result)

    def confirmation_action(self, action: ToolAction, state_version: int) -> ToolAction | None:
        return MultiTaskRuntime._confirmation_action(action, state_version)

    def confirmation_matches(self, original: ToolAction, result: StepResult) -> bool:
        return MultiTaskRuntime._confirmation_matches(original, result)


class RetailRuntimeHooks:
    domain = "retail"
    _write_tools = {
        "cart.add_item",
        "cart.apply_coupon",
        "orders.place_order",
        "retail.resolve_purchase_request",
        "refunds.issue_partial_refund",
        "retail.resolve_refund_request",
    }

    def is_write(self, action: ToolAction) -> bool:
        return action.tool_name in self._write_tools

    def result_contract_valid(
        self,
        environment: RuntimeEnvironment,
        action: ToolAction,
        result: StepResult,
    ) -> bool:
        if not isinstance(environment, RetailEnvironment):
            raise TypeError("Retail hooks require RetailEnvironment")
        return RetailRuntime._result_contract_valid(environment, action, result)

    def confirmation_action(self, action: ToolAction, state_version: int) -> ToolAction | None:
        return RetailRuntime._confirmation_action(action, state_version)

    def confirmation_matches(self, original: ToolAction, result: StepResult) -> bool:
        return RetailRuntime._confirmation_matches(original, result)


@dataclass(frozen=True)
class SmokeTaskAdapter:
    blueprint: TaskBlueprint
    expected_fault_id: str

    @property
    def template_id(self) -> str:
        return self.blueprint.template_id

    @property
    def task_id(self) -> str:
        return self.blueprint.task_id

    @property
    def domain(self) -> str:
        return self.blueprint.domain

    def create_environment(
        self, condition: str
    ) -> MultiTaskWorkspaceEnvironment | RetailEnvironment:
        if condition not in {"clean", "recoverable_fault"}:
            raise ValueError(f"Unknown smoke condition: {condition}")
        faulted = condition == "recoverable_fault"
        if self.task_id == WORKSPACE_TASK_ID:
            return MultiTaskWorkspaceEnvironment(
                fault_mode="event_postcommit_timeout_once" if faulted else "none"
            )
        if self.task_id == PURCHASE_TASK_ID:
            return RetailEnvironment(
                fault_mode="order_postcommit_timeout_once" if faulted else "none"
            )
        raise ValueError(f"No smoke environment adapter for {self.task_id}")

    def semantic_actions(self, observation: Observation) -> tuple[ToolAction, ...]:
        if self.task_id == WORKSPACE_TASK_ID:
            return _semantic(workspace_task_actions(observation, "r1_guarded"))
        if self.task_id == PURCHASE_TASK_ID:
            return _semantic(retail_task_actions(observation, "r1_guarded"))
        raise ValueError(f"No smoke policy adapter for {self.task_id}")

    def runtime_hooks(self) -> WorkspaceRuntimeHooks | RetailRuntimeHooks:
        if self.task_id == WORKSPACE_TASK_ID:
            return WorkspaceRuntimeHooks()
        if self.task_id == PURCHASE_TASK_ID:
            return RetailRuntimeHooks()
        raise ValueError(f"No smoke runtime hooks for {self.task_id}")

    def evaluate(
        self,
        pre_snapshot: SnapshotRef,
        post_snapshot: SnapshotRef,
        trace_events: Sequence[dict[str, Any]],
    ) -> EvaluationReport:
        if self.task_id == WORKSPACE_TASK_ID:
            return evaluate_workspace_multitask(pre_snapshot, post_snapshot, trace_events)
        if self.task_id == PURCHASE_TASK_ID:
            return evaluate_retail(pre_snapshot, post_snapshot, trace_events)
        raise ValueError(f"No smoke evaluator for {self.task_id}")


SMOKE_ADAPTERS = {
    BLUEPRINTS_BY_TASK_ID[WORKSPACE_TASK_ID].template_id: SmokeTaskAdapter(
        blueprint=BLUEPRINTS_BY_TASK_ID[WORKSPACE_TASK_ID],
        expected_fault_id="fault.workspace.event.postcommit_timeout_once",
    ),
    BLUEPRINTS_BY_TASK_ID[PURCHASE_TASK_ID].template_id: SmokeTaskAdapter(
        blueprint=BLUEPRINTS_BY_TASK_ID[PURCHASE_TASK_ID],
        expected_fault_id="fault.retail.order.postcommit_timeout_once",
    ),
}

if tuple(SMOKE_ADAPTERS) != SMOKE_TEMPLATE_IDS:  # pragma: no cover - import-time gate
    raise RuntimeError("Smoke adapter order drifted from the frozen template order")
