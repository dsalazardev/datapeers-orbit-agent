"""Domain errors for the ingestion capability.

These exceptions carry stable, client-safe reason codes so the HTTP adapter can
map them to responses without ever exposing raw exception text (ORB-NFR-005).
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for ingestion errors."""


class UrlRejected(IngestionError):
    """The submitted URL is not an acceptable ingestion target."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


class DnsResolutionError(IngestionError):
    """The host could not be resolved (lookup failure, timeout or empty result)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail
