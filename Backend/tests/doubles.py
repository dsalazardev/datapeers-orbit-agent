"""Test doubles implementing the application ports (design D11)."""

from __future__ import annotations

from typing import Awaitable, Callable, Sequence
from uuid import UUID

from app.modules.ingestion.domain.errors import DnsResolutionError


class FakeHostResolver:
    """Resolver double: returns fixed addresses or raises a scripted error."""

    def __init__(
        self,
        addresses: Sequence[str] | None = None,
        error: str | None = None,
    ) -> None:
        self.addresses = list(addresses or [])
        self.error = error
        self.resolved_hosts: list[str] = []

    async def resolve(self, host: str) -> Sequence[str]:
        self.resolved_hosts.append(host)
        if self.error is not None:
            raise DnsResolutionError(self.error)
        return list(self.addresses)


class RecordingScheduler:
    """Scheduler double that records jobs WITHOUT executing them (N1)."""

    def __init__(self) -> None:
        self.jobs: list[Callable[[], Awaitable[None]]] = []

    def schedule(self, job: Callable[[], Awaitable[None]]) -> None:
        self.jobs.append(job)


class RecordingPipeline:
    """Pipeline double that records invocations so tests can assert non-execution."""

    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def run(self, onboarding_id: UUID) -> None:
        self.calls.append(onboarding_id)
