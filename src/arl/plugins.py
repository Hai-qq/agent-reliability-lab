"""Reserved lightweight entry-point groups for optional third-party adapters."""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points

ENTRY_POINT_GROUPS = (
    "arl.environments",
    "arl.faults",
    "arl.runtimes",
    "arl.providers",
)


def discover(group: str) -> tuple[EntryPoint, ...]:
    """Discover but do not import adapters in one declared ARL plugin group."""

    if group not in ENTRY_POINT_GROUPS:
        raise ValueError(f"unknown ARL entry-point group: {group}")
    return tuple(entry_points(group=group))


__all__ = ["ENTRY_POINT_GROUPS", "discover"]
