"""LLM batch classification for the pre-scraper (design D1-D3).

Single module owning: (a) the strict ``ProjectCard`` Pydantic schema (an internal
DTO that never travels to the API), (b) the Spanish system prompt that fixes the
JSON contract and forbids price hallucination, (c) ``LLMProjectClassifier`` (the
async client doing one batch call per request), and (d) the mapping from
``ProjectCard`` onto the additive ``ProjectItem`` fields.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.modules.scraping.schemas import ProjectItem

logger = logging.getLogger("orbit.scraping")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

StatusBadge = Literal["Preventa", "Entrega Inmediata", "Agotado", "Desconocido"]


class ProjectCard(BaseModel):
    """Strict schema of the LLM answer for ONE candidate (position 1..N).

    Internal DTO: it is validated on every response and never exposed through
    the API (``description_summary`` stays internal, design D6).
    """

    is_project: bool
    is_active_project: bool
    title: str
    description_summary: str | None = None
    price_from: str | None = None
    status_badge: StatusBadge
    score: int = Field(ge=0, le=100)


SYSTEM_PROMPT: str = """Eres un clasificador inmobiliario. Recibes una lista de candidatos extraídos \
del HTML de un sitio de una constructora o inmobiliaria. Cada candidato tiene un índice (1..N), \
un título, una URL y una fuente (meta/card/link).

Debes responder ÚNICAMENTE un array JSON válido, con exactamente un objeto por candidato, en el \
mismo orden de los índices. NO agregues texto, ni markdown, ni explicaciones. El objeto de cada \
candidato debe tener exactamente esta forma:

{
  "is_project": true|false,
  "is_active_project": true|false,
  "title": "título del proyecto tal como aparece en el HTML",
  "description_summary": "resumen breve en español de una frase o null si no hay descripción",
  "price_from": "valor numérico con unidades (ej. \"$520.000.000\" o \"$4.500 UF\") o null si el HTML no muestra precio",
  "status_badge": "Preventa" | "Entrega Inmediata" | "Agotado" | "Desconocido",
  "score": 0-100
}

REGLAS:
- "is_project" es true solo si la URL corresponde a un proyecto inmobiliario (apartamentos, casas, \
torres, etapas, unidades). false para blogs, noticias, contactos, empleos, folletos, páginas legales \
o cualquier contenido no inmobiliario.
- "is_active_project" es true si el proyecto está comercializándose actualmente (en preventa, con \
unidades disponibles o en entrega reciente); false si está agotado, terminado o descatalogado; usa \
preferentemente "Desconocido" en el status cuando no haya señales claras.
- "price_from": SOLO usa un precio si el HTML lo muestra explícitamente (sí escribe el número y la \
unidad tal cual). Si el HTML NO muestra precio, escribe null. NUNCA inventes ni infierras precios.
- "status_badge": usa exactamente uno de los cuatro valores permitidos.
- "score": tu confianza de que es un proyecto inmobiliario, de 0 (nada seguro) a 100 (totalmente seguro).
- "description_summary": una frase breve en español o null.
- Mantén el título lo más parecido al texto del HTML.

RESPONDE SOLO EL JSON."""


def _extract_json_payload(content: str) -> list[dict]:
    """Robust extraction of the JSON array from a model answer (design D2).

    Strips `` ```json `` fences when present, decodes the JSON and requires a
    top-level list. Raises ``ValueError`` on any structural problem so callers
    can fall back without propagating raw content.
    """
    text = content.strip()
    if text.startswith("```"):
        first_eol = text.find("\n")
        if first_eol != -1:
            text = text[first_eol:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    elif text.startswith("`"):
        text = text.strip("`")
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("respuesta LLM no es un array")
    return payload


def _align_cards(
    cards: list[ProjectCard], expected: int
) -> list[ProjectCard] | None:
    """Return ``cards`` only when it validates and aligns 1:1 with candidates."""
    if len(cards) != expected:
        return None
    return cards


class LLMProjectClassifier:
    """Async client that classifies a batch of candidates in ONE call (D2/D3).

    Never reintants the call: network errors, timeouts, non-2xx, invalid schema
    or misalignment collapse into ``None`` so the service applies the
    deterministic fallback (D4). The API key is only used in the Authorization
    header and is never logged.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: float = 8.0,
        max_tokens: int = 4096,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(transport=self._transport)
        return self._client

    async def classify(self, items: list[ProjectItem]) -> list[ProjectCard] | None:
        """Classify a batch of ProjectItems in a single LLM call.

        Returns the aligned ``ProjectCard`` list or ``None`` to request fallback.
        """
        if not items:
            return []
        n = len(items)
        try:
            client = self._get_client()
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": _build_batch_prompt(items),
                        },
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": self._max_tokens,
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError:
            logger.warning(
                "llm_classification_failed",
                extra={"evt": "llm_classification_fallback", "phase": "transport"},
            )
            return None
        if response.status_code >= 400:
            logger.warning(
                "llm_classification_http_error", extra={"status_code": response.status_code}
            )
            return None
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            payload = _extract_json_payload(content)
            cards = [ProjectCard.model_validate(card) for card in payload]
        except (KeyError, ValueError, ValidationError):
            logger.warning(
                "llm_classification_invalid_schema",
                extra={"evt": "llm_classification_fallback", "phase": "schema"},
            )
            return None
        return _align_cards(cards, n)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> LLMProjectClassifier:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()


def _build_batch_prompt(items: list[ProjectItem]) -> str:
    """Serialize the candidate batch as an indexed user message (D2)."""
    lines = ["Clasifica cada candidato y devuelve el array JSON alineado:"]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {item.title} | fuente: {item.source}")
    return "\n".join(lines)


def map_card_to_item(item: ProjectItem, card: ProjectCard) -> ProjectItem:
    """Apply the additive LLM fields onto a ProjectItem (design D6).

    ``description_summary`` stays internal and is not exposed on the API.
    """
    return item.model_copy(
        update={
            "is_active_project": card.is_active_project,
            "status_badge": card.status_badge,
            "price_from": card.price_from,
        }
    )