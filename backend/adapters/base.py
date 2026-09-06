"""
Adapter SDK — base contract every execution adapter must implement.
New technologies integrate here without touching core logic.

Section 83 of SSOT: discover / connect / authenticate / execute /
observe / reset / snapshot / restore / collect_evidence
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.core.ontology import EvidenceBundle, Scenario


class AdapterCapability(str):
    DISCOVER = "discover"
    EXECUTE = "execute"
    OBSERVE = "observe"
    RESET = "reset"
    SNAPSHOT = "snapshot"
    RESTORE = "restore"
    FAULT_INJECT = "fault_inject"


class ExecutionAdapter(ABC):
    """
    Base class for all UASAE execution adapters.
    One adapter per technology domain (browser, api, database, events, …).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier, e.g. 'playwright', 'httpx', 'psycopg'."""

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """Which AdapterCapability values this adapter supports."""

    @abstractmethod
    async def connect(self, config: dict[str, Any]) -> None:
        """Establish connection to the target system."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up connections."""

    @abstractmethod
    async def execute(self, scenario: Scenario) -> EvidenceBundle:
        """Execute one scenario and return a complete evidence bundle."""

    async def reset(self, environment: str) -> None:
        raise NotImplementedError(f"{self.name} does not support reset")

    async def snapshot(self, environment: str) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not support snapshot")

    async def restore(self, environment: str, snapshot: dict[str, Any]) -> None:
        raise NotImplementedError(f"{self.name} does not support restore")

    async def discover(self) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not support discover")
