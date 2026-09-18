"""LLM batch classification for the pre-scraper (design D1-D3).

Single module owning: (a) the strict ``ProjectCard`` Pydantic schema (an internal
DTO that never travels to the API), (b) the Spanish system prompt that fixes the
JSON contract and forbids price hallucination, (c) ``LLMProjectClassifier`` (the
async client doing one batch call per request), and (d) the mapping from
``ProjectCard`` onto the additive ``ProjectItem`` fields.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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