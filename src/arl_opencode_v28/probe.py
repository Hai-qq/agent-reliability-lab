"""Digest-only two-turn structured-tool probe for the v0.28 Qwen binding."""

from __future__ import annotations

from typing import Any

from arl.core.types import digest_value
from arl_mainstudy.model import (
    ModelProtocolError,
    ModelRequest,
    SamplingConfig,
    ToolDefinition,
)
from arl_modelpilot.deepseek import PROMPT_CONTRACT_VERSION, DeepSeekBackendError

from .backend import OpenCodeQwenV28Backend
from .contract import QWEN_BINDING

PROBE_TASK_ID = "opencode_go.protocol_probe"
PROBE_TOOL = ToolDefinition("probe.echo", "v1", ("value",))
PROBE_VALUE = "arl-v028-synthetic-probe"
PROBE_SAMPLING = SamplingConfig(0.0, 1.0, 256, None)


def _request(*, turn_index: int, feedback: dict[str, Any] | None) -> ModelRequest:
    return ModelRequest(
        prompt_contract_version=PROMPT_CONTRACT_VERSION,
        binding=QWEN_BINDING,
        task_id=PROBE_TASK_ID,
        turn_index=turn_index,
        observation={
            "visible_task": {
                "user_request": "Call the supplied echo tool once, then finish after success.",
                "context": {"value": PROBE_VALUE},
            }
        },
        feedback=feedback,
        tools=(PROBE_TOOL,),
        sampling=PROBE_SAMPLING,
    )


def run_qwen_protocol_probe(
    backend: OpenCodeQwenV28Backend,
    *,
    catalog_attestation: dict[str, Any],
) -> dict[str, Any]:
    """Exercise tool-call then tool-feedback semantics without persisting content."""

    failure_code: str | None = None
    failure_detail_sha256: str | None = None
    first_kind: str | None = None
    first_tool_name: str | None = None
    first_arguments_sha256: str | None = None
    first_arguments_match = False
    second_kind: str | None = None
    try:
        first = backend.generate(_request(turn_index=0, feedback=None))
        first_kind = first.kind
        first_tool_name = first.tool_name
        first_arguments_sha256 = (
            digest_value(first.arguments) if isinstance(first.arguments, dict) else None
        )
        first_arguments_match = first.arguments == {"value": PROBE_VALUE}
        if first.kind != "tool" or first.tool_name != PROBE_TOOL.tool_name:
            raise ModelProtocolError("Probe did not select the exact synthetic echo tool")
        PROBE_TOOL.validate_arguments(first.arguments or {})
        if not first_arguments_match:
            raise ModelProtocolError("Probe tool arguments did not match the fixed contract")
        second = backend.generate(
            _request(
                turn_index=1,
                feedback={
                    "status": "ok",
                    "result_sha256": digest_value({"value": PROBE_VALUE}),
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
    transport_audit = backend.transport_audit_records()
    checks = {
        "authenticated_catalog_attestation": catalog_attestation.get("passed") is True,
        "exact_qwen_binding": all(
            call["requested_model"] == QWEN_BINDING.model_id for call in calls
        ),
        "provider_returned_qwen": bool(calls)
        and all(
            call["response_model"] == QWEN_BINDING.model_id
            for call in calls
            if call["status"] == "ok"
        ),
        "first_turn_exact_tool_call": first_kind == "tool"
        and first_tool_name == PROBE_TOOL.tool_name
        and first_arguments_match,
        "second_turn_finished_after_feedback": second_kind == "finish",
        "zero_typed_failures": failure_code is None,
        "two_logical_calls": len(calls) == 2,
    }
    return {
        "metadata": {
            "probe_version": "arl-opencode-go-qwen-protocol-probe-v0.28.0",
            "provider_content_persisted": False,
            "task_contract_sha256": digest_value(
                {
                    "task_id": PROBE_TASK_ID,
                    "tool": PROBE_TOOL.as_dict(),
                    "value": PROBE_VALUE,
                    "sampling": PROBE_SAMPLING.as_dict(),
                }
            ),
        },
        "binding": QWEN_BINDING.as_dict(),
        "catalog_attestation": catalog_attestation,
        "decisions": {
            "first_kind": first_kind,
            "first_tool_name": first_tool_name,
            "first_arguments_sha256": first_arguments_sha256,
            "first_arguments_match": first_arguments_match,
            "second_kind": second_kind,
        },
        "provider_calls": calls,
        "transport_audit": transport_audit,
        "failure_code": failure_code,
        "failure_detail_sha256": failure_detail_sha256,
        "checks": checks,
        "passed": all(checks.values()),
    }
