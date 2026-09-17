"""DNS resolution adapter for destination validation (design D7).

Resolves the host in a worker thread (`anyio.to_thread`) with a timeout. A
timeout and an empty result are distinct from a blocked address: both map to
`DnsResolutionError` so the use case reports `dns_resolution_failed` instead of
the silent-failure case `address_not_allowed`.
"""

from __future__ import annotations

import socket

import anyio

from app.modules.ingestion.domain.errors import DnsResolutionError

DEFAULT_TIMEOUT_SECONDS = 5.0


class SystemHostResolver:
    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    async def resolve(self, host: str) -> list[str]:
        infos: list = []
        try:
            with anyio.move_on_after(self._timeout) as scope:
                # abandon_on_cancel=True is required so the deadline actually
                # cancels the await: with the default (False) the await is
                # shielded, the scope never reports cancelled_caught, and a
                # hung DNS would come back as an empty result instead of a
                # timeout (silent failure found in review).
                infos = await anyio.to_thread.run_sync(
                    socket.getaddrinfo,
                    host,
                    None,
                    0,
                    socket.SOCK_STREAM,
                    abandon_on_cancel=True,
                )
        except OSError as exc:
            raise DnsResolutionError("lookup_failed") from exc

        if scope.cancelled_caught:
            raise DnsResolutionError("timeout")
        if not infos:
            raise DnsResolutionError("empty")

        addresses: dict[str, None] = {}
        for info in infos:
            addresses.setdefault(info[4][0], None)
        return list(addresses)
