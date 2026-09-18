"""Stable reason-code catalog and safe error DTO for the scraping module.

All router errors must carry a stable `ORB-SCRAPE-XXX` reason code; raw
exception text is never exposed to the client (ORB-NFR-005).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ScrapeReasonCode(str, Enum):
    INTERNAL_ERROR = "ORB-SCRAPE-000"  # fallback genérico (500)
    FETCH_FAILED = "ORB-SCRAPE-001"  # red/timeout/URL inalcanzable
    PARSE_FAILED = "ORB-SCRAPE-002"  # HTML malformado o extracción fallida
    INVALID_RESPONSE = "ORB-SCRAPE-003"  # respuesta sin ítems válidos construibles
    UPSTREAM_BLOCKED = "ORB-SCRAPE-004"  # 403/robots/WAF/CDN detectado (reservado)
    CACHE_UNAVAILABLE = "ORB-SCRAPE-005"  # caché/seed inaccesible (reservado)
    LLM_UNAVAILABLE = "ORB-SCRAPE-006"  # clasificador LLM no disponible (log-only)


HTTP_STATUS_BY_CODE: Mapping[ScrapeReasonCode, int] = {
    ScrapeReasonCode.INTERNAL_ERROR: 500,
    ScrapeReasonCode.FETCH_FAILED: 502,
    ScrapeReasonCode.PARSE_FAILED: 502,
    ScrapeReasonCode.INVALID_RESPONSE: 500,
    ScrapeReasonCode.UPSTREAM_BLOCKED: 502,
    ScrapeReasonCode.CACHE_UNAVAILABLE: 500,
}

DEFAULT_MESSAGE_BY_CODE: Mapping[ScrapeReasonCode, str] = {
    ScrapeReasonCode.INTERNAL_ERROR: "Ocurrió un error inesperado.",
    ScrapeReasonCode.FETCH_FAILED: "No se pudo cargar el sitio de origen.",
    ScrapeReasonCode.PARSE_FAILED: "No se pudo interpretar el contenido del sitio.",
    ScrapeReasonCode.INVALID_RESPONSE: "La respuesta del sitio no contiene proyectos válidos.",
    ScrapeReasonCode.UPSTREAM_BLOCKED: "El sitio de origen bloqueó la solicitud.",
    ScrapeReasonCode.CACHE_UNAVAILABLE: "La caché del pre-scrape no está disponible.",
}


@dataclass(frozen=True, slots=True)
class ScrapeError(Exception):
    """Domain error carrying a safe, stable reason code (never raw text)."""

    reason_code: ScrapeReasonCode
    message: str

    @classmethod
    def for_code(cls, code: ScrapeReasonCode, message: str | None = None) -> ScrapeError:
        return cls(reason_code=code, message=message or DEFAULT_MESSAGE_BY_CODE[code])


def error_payload(
    error: ScrapeError, request_id: str = "-"
) -> dict[str, Any]:
    """Build the normalized error body sent to the client."""
    status = HTTP_STATUS_BY_CODE[error.reason_code]
    return {
        "error": {
            "reason_code": str(error.reason_code.value),
            "message": error.message,
            "request_id": request_id,
            "http_status": status,
        }
    }