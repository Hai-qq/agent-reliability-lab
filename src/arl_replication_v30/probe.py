"""Digest-only repeated protocol and availability probe for both v0.30 bindings."""

from __future__ import annotations

from typing import Any

from arl.core.types import digest_value
from arl_mainstudy.model import ModelProtocolError, ModelRequest, SamplingConfig, ToolDefinition
from arl_modelpilot.deepseek import PROMPT_CONTRACT_VERSION, DeepSeekBackendError

from .backend import OpenCodeV30Backend, backend_for_slot
from .contract import MODEL_BINDINGS

PROBE_REPETITIONS = 3
PROBE_TOOL = ToolDefinition("probe.echo", "v1", ("value",))
PROBE_SAMPLING = SamplingConfig(0.0, 1.0, 256, None)


def _request(
    *,
    slot_id: str,
    repetition: int,
    turn_index: int,
    value: str,
    feedback: dict[str, Any] | None,
) -> ModelRequest:
    return ModelRequest(
        prompt_contract_version=PROMPT_CONTRACT_VERSION,
        binding=MODEL_BINDINGS[slot_id],
        task_id=f"opencode_go.v30.availability_probe.{slot_id}.r{repetition}",
        turn_index=turn_index,
        observation={
            "visible_task": {
                "user_request": "Call the supplied echo tool once, then finish after success.",
                "context": {"value": value},
            }
        },
        feedback=feedback,
        tools=(PROBE_TOOL,),
        sampling=PROBE_SAMPLING,
    )


def _run_repetition(
    slot_id: str,
    repetition: int,
    backend: OpenCodeV30Backend,
    *,
    catalog_attestation: dict[str, Any],
) -> dict[str, Any]:
    value = f"arl-v030-synthetic-probe-{slot_id}-r{repetition}"
    failure_code: str | None = None
    failure_detail_sha256: str | None = None
    first_kind: str | None = None
    first_tool_name: str | None = None
    first_arguments_sha256: str | None = None
    first_arguments_match = False
    second_kind: str | None = None
    try:
        first = backend.generate(
            _request(
                slot_id=slot_id,
                repetition=repetition,
                turn_index=0,
                value=value,
                feedback=None,
            )
        )
        first_kind = first.kind
        first_tool_name = first.tool_name
        first_arguments_sha256 = (
            digest_value(first.arguments) if isinstance(first.arguments, dict) else None
        )
        first_arguments_match = first.arguments == {"value": value}
        if first.kind != "tool" or first.tool_name != PROBE_TOOL.tool_name:
            raise ModelProtocolError("Probe did not select the exact synthetic echo tool")
        PROBE_TOOL.validate_arguments(first.arguments or {})
        if not first_arguments_match:
            raise ModelProtocolError("Probe tool arguments did not match the fixed contract")
        second = backend.generate(
            _request(
                slot_id=slot_id,
                repetition=repetition,
                turn_index=1,
                value=value,
                feedback={
                    "status": "ok",
                    "result_sha256": digest_value({"value": value}),
                },
            )
        )
        second_kind = second.kind
        if second.kind != "finish":
            raise ModelProtocolError("Probe did not finish after successful tool feedback")
    except DeepSeekBackendError as error:
        failure_code = error.error_code
        failure_detail_sha256 = digest_value(str(error))
    except (ModelProtocolError, ValueError, TypeError) as error:
        failure_code = (
            "model_protocol_error"
            if isinstance(error, ModelProtocolError)
            else "probe_local_validation_error"
        )
        failure_detail_sha256 = digest_value(str(error))

    calls = [record.as_dict() for record in backend.call_records]
    transport = backend.transport_audit_records()
    reservations = backend.budget_reservation_records()
    binding = MODEL_BINDINGS[slot_id]
    checks = {
        "authenticated_catalog_attestation": catalog_attestation.get("passed") is True,
        "exact_binding": all(call["requested_model"] == binding.model_id for call in calls),
        "provider_returned_requested_model": bool(calls)
        and all(
            call["response_model"] == binding.model_id for call in calls if call["status"] == "ok"
        ),
        "non_thinking_inference": bool(calls)
        and all(call["thinking_mode"] == "disabled" for call in calls),
        "first_turn_exact_tool_call": first_kind == "tool"
        and first_tool_name == PROBE_TOOL.tool_name
        and first_arguments_match,
        "second_turn_finished_after_feedback": second_kind == "finish",
        "zero_typed_failures": failure_code is None,
        "two_logical_calls": len(calls) == 2,
        "two_pre_dispatch_reservations": len(reservations) == 2
        and all(item["allowed"] and item["actual_within_reservation"] for item in reservations),
        "bounded_transport_audit": len(transport) == len(calls),
    }
    return {
        "repetition": repetition,
        "binding": binding.as_dict(),
        "decisions": {
            "first_kind": first_kind,
            "first_tool_name": first_tool_name,
            "first_arguments_sha256": first_arguments_sha256,
            "first_arguments_match": first_arguments_match,
            "second_kind": second_kind,
        },
        "provider_calls": calls,
        "transport_audit": transport,
        "budget_reservations": reservations,
        "failure_code": failure_code,
        "failure_detail_sha256": failure_detail_sha256,
        "checks": checks,
        "passed": all(checks.values()),
    }


def run_protocol_probe(
    *, api_key: str, timeout_seconds: float, catalog_attestation: dict[str, Any]
) -> dict[str, Any]:
    by_model: dict[str, Any] = {}
    for slot in ("flash", "pro"):
        repetitions = [
            _run_repetition(
                slot,
                repetition,
                backend_for_slot(slot, api_key=api_key, timeout_seconds=timeout_seconds),
                catalog_attestation=catalog_attestation,
            )
            for repetition in range(PROBE_REPETITIONS)
        ]
        calls = [call for item in repetitions for call in item["provider_calls"]]
        transport = [audit for item in repetitions for audit in item["transport_audit"]]
        by_model[slot] = {
            "binding": MODEL_BINDINGS[slot].as_dict(),
            "repetitions": repetitions,
            "provider_calls": calls,
            "logical_call_count": len(calls),
            "external_attempt_count": sum(item["attempt_count"] for item in transport),
            "transport_retry_count": sum(item["attempt_count"] - 1 for item in transport),
            "passed": len(repetitions) == PROBE_REPETITIONS
            and all(item["passed"] for item in repetitions),
        }
    logical_calls = sum(item["logical_call_count"] for item in by_model.values())
    return {
        "metadata": {
            "probe_version": "arl-opencode-go-two-model-availability-probe-v0.30.0",
            "provider_content_persisted": False,
            "task_contract_sha256": digest_value(
                {
                    "tool": PROBE_TOOL.as_dict(),
                    "sampling": PROBE_SAMPLING.as_dict(),
                    "slots": ["flash", "pro"],
                    "repetitions_per_slot": PROBE_REPETITIONS,
                }
            ),
        },
        "catalog_attestation": catalog_attestation,
        "by_model": by_model,
        "repetitions_per_model": PROBE_REPETITIONS,
        "logical_call_count": logical_calls,
        "external_attempt_count": sum(item["external_attempt_count"] for item in by_model.values()),
        "transport_retry_count": sum(item["transport_retry_count"] for item in by_model.values()),
        "passed": logical_calls == 12 and all(item["passed"] for item in by_model.values()),
    }
