"""Stable public package for Agent Reliability Lab."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-reliability-lab")
except PackageNotFoundError:  # Source-only checkout before installation.
    __version__ = "0+unknown"

__all__ = ["__version__"]
