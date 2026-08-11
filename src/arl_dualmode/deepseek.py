"""Thinking-high adapter layered over the frozen v0.24 DeepSeek backend."""

from __future__ import annotations

from dataclasses import replace

from arl_mainstudy.model import ModelDecision, ModelRequest
from arl_modelpilot.deepseek import DeepSeekChatBackend

from .contract import FLASH_THINKING_HIGH_BINDING

THINKING_MODE = "enabled"
REASONING_EFFORT = "high"


class DeepSeekFlashThinkingBackend(DeepSeekChatBackend):
    """Use the same DeepSeek V4 Flash model with thinking enabled at high effort."""

    binding = FLASH_THINKING_HIGH_BINDING

    def _request_payload(self, request: ModelRequest) -> dict[str, object]:
        payload = super()._request_payload(request)
        payload["thinking"] = {"type": THINKING_MODE}
        payload["reasoning_effort"] = REASONING_EFFORT
        return payload

    def generate(self, request: ModelRequest) -> ModelDecision:
        """Relabel new digest-only records without changing the frozen base module."""

        start_index = len(self.call_records)
        try:
            return super().generate(request)
        finally:
            for index in range(start_index, len(self.call_records)):
                self.call_records[index] = replace(
                    self.call_records[index],
                    thinking_mode=THINKING_MODE,
                )
