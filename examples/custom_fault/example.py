"""Minimal deterministic custom fault injector."""

from __future__ import annotations

from typing import Any

from arl.faults import FaultInjector


class AckLossOnce:
    @property
    def fault_id(self) -> str:
        return "example.ack_loss.once.v1"

    def inject(self, *, sequence_index: int, state: dict[str, Any]) -> dict[str, Any]:
        active = sequence_index == 2 and state.get("committed") is True
        return {
            "fault_id": self.fault_id,
            "active": active,
            "observable_symptom": "typed_timeout" if active else "none",
        }


fault: FaultInjector = AckLossOnce()
print(fault.inject(sequence_index=2, state={"committed": True}))
