## Context

El módulo scraping (`Backend/app/modules/scraping/`) quedó refactorizado en P0 con `config.py`, `parser.py`, `cache.py`, `errors.py`, `schemas.py` y `service.py` (`PreScraperService`). El flujo es determinista: parseo (thread pool vía `anyio`) → extracción de candidatos con cascada meta/cards/links → filtros por keywords negativas, agrupadores y títulos débiles → normalización a `ProjectItem` → respuesta de `POST /api/v1/scraping/pre-scrape` (máx. 10 ítems). La caché JSON y el seeded fallback resuelven en <200ms si no hay red.

El límite actual es de precisión semántica: las reglas deterministas no distinguen de forma fiable "proyecto" de "blog", "cuota" de "precio", ni detectan estado (preventa/entrega) o precio. La clasificación con LLM fue diferida a P1 en el cambio archivado `refactor-pre-scraper-stability`. Este change implementa ese P1 como **motor híbrido**: se mantiene la extracción determinista y se añade una validación semántica en batch por el LLM solo en el flujo `live`, con fallback determinista garantizado.

No existe todavía ninguna dependencia LLM en el repo (`httpx` como cliente async ya está presente). El modelo por defecto `deepseek/deepseek-v4-flash-0731:free` está verificado disponible en OpenRouter (`https://openrouter.ai/api/v1/models`, variante free-tier).

## Goals / Non-Goals

**Goals:**
- Añadir clasificación semántica LLM entre la extracción determinista y la respuesta final, descartando `is_project == false`.
- UNA sola llamada batch por solicitud (máx. 10 candidatos), exige structured output JSON validado contra un esquema Pydantic estricto (`ProjectCard`).
- Enriquecer `ProjectItem` de forma aditiva (`is_active_project`, `status_badge`, `price_from`) sin romper el contrato existente (`title`, `url`, `source`).
- Fallback determinista silencioso sin API key, con timeout (8s) o ante error de red/HTTP/esquema; nunca un error 500 al usuario por causa del LLM.
- No bloquear el event loop (I/O `await`), resolver cache/seed sin invocar el LLM, y cero llamadas reales en la suite (mocks).
- Precisión `is_project` ≥ 90% y cero alucinaciones de `price_from` sobre un golden dataset de 10 URLs reales.

**Non-Goals:**
- RAG, vector DB o embeddings.
- Deep scraping de fichas de proyecto.
- Rediseño del frontend / migración Tailwind (change separado).
- Modificar ingestion o la capa de caché (la caché sigue guardando ítems pre-clasificación).
- Modelos por encima de peso ligero (≤ ~10B o flash-tier).
- Streaming/SSE de la clasificación.

## Decisions

### D1: Módulo único `app/modules/scraping/llm.py`

Se crea un único archivo `llm.py` en el paquete del módulo que concentra: (a) `ProjectCard` (esquema Pydantic estricto de la respuesta del LLM, DTO interno que NO viaja al API), (b) el prompt del sistema en español con el contrato JSON y la instrucción de no inventar precios, (c) `LLMProjectClassifier` (cliente async) responsable de la llamada batch, el parseo robusto del JSON y la validación, y (d) el mapeo de `ProjectCard` → campos aditivos de `ProjectItem`.

**Alternativa descartada**: subpaquete `classifier/` (port + adapters + prompts + schemas). Se descarta porque el alcance cabe en un solo responsable y el módulo mantiene su layout plano a propósito (decisión D1 del P0). Si el deep-scraping o ingestion requieren clasificar en el futuro, se promueve a capacidad top-level en ese momento, no antes.

### D2: Batching — una llamada por solicitud

La llamada incluye los ≤10 candidatos (`title`, `url`, `source`) en un único `user` message con índices 1..N y exige una respuesta JSON estructurada alineada a esos índices. Razones: (1) minimiza latencia y coste (1 round-trip), (2) el límite natural de 10 ítems hace innecesaria la segmentación en múltiples llamadas, y (3) simplifica el fallback (todo o nada). La petición usa `response_format: {"type": "json_object"}`, cuyo soporte fue **verificado en vivo** (2026-09-17) sobre `deepseek/deepseek-v4-flash-0731:free`: devolvió `finish_reason=stop` y JSON válido con coste 0. **Ajuste de contrato verificado (2026-09-17)**: con `json_object`, el modelo free responde un OBJETO top-level, no un array — por lo que el contrato de respuesta es un objeto indexado `{"1": {...}, "2": {...}}` con una clave por candidato en orden 1..N (compatible con `json_object` y con la alineación 1:1). El parseo robusto acepta tanto el objeto indexado como un array plano (defensa en profundidad ante modelos que ignoren el shape), y exige `len(respuesta) == len(candidatos)`; si no alinea o no valida contra `ProjectCard` → fallback completo.

### D3: Cliente HTTP y no-bloqueo

Se usa `httpx.AsyncClient` dedicado (independiente del client de fetch del servicio) apuntando a `{base_url}/chat/completions` con headers `Authorization: Bearer {api_key}`. Toda la llamada es `await` de I/O en el event loop — sin `parse HTML` CPU-bound, por lo que NO se usa `to_thread`. El client comparte la política de timeout configurable (`ORBIT_LLM_TIMEOUT`, default 8s) aplicada por llamada, y NO reintenta: una sola llamada estricta; la resiliencia recae en el fallback determinista (D4) para no degradar la latencia P95. Un único `AsyncClient` se construye en el wiring y se cierra en el lifespan de la app; alternativa aceptada en tests: inyección de transporte (`httpx.MockTransport`) para cero llamadas reales.

### D4: Fallback determinista y logging

Reglas de decisión, en orden:
1. Sin `api_key` configurada → no se instancia client real; flujo `live` devuelve ítems deterministas con `is_active_project = None`, sin invocar el LLM.
2. Llamada OK → validación `ProjectCard` OK y alineación 1:1 (`len(respuesta) == len(candidatos)` con índices alineados) → enriquecer ítems, descartar `is_project == false` y reportar los descartes en `meta.filtered_out`.
3. Timeout estricto (8s, sin reintentos), error de red, HTTP no-2xx, JSON/schema inválido o desalineación del batch → ítems deterministas con `is_active_project = None` (y `status_badge`/`price_from` en `None`), log estructurado con `evt=llm_classification_fallback`, `source=fallback` y `reason_code=ORB-SCRAPE-006`.
4. Cero ítems post-filtro → si el LLM descarta todos los candidatos (`is_project == false` en todos), la respuesta es `200 OK` con `items: []` y `meta.filtered_out = N` (número de candidatos descartados), sin generar un error.

`errors.py` incorpora `LLM_UNAVAILABLE = "ORB-SCRAPE-006"` como código **log-only** (no se expone al cliente): el fallback es funcional y no debe producir un 5xx. La propiedad `Seguridad`: nunca se loggea la API key ni el contenido crudo de la excepción (ORB-NFR-005).

### D5: Integración en `PreScraperService`

`PreScraperService` recibe `classifier: LLMProjectClassifier | None = None`. En el flujo `live`, DESPUÉS de normalizar candidatos a `ProjectItem` y ANTES de la respuesta final: si hay `classifier` y `api_key`, clasificar, descartar `is_project == false`, aplicar campos aditivos, reportar descartes en `meta.filtered_out` y volver a aplicar el tope `MAX_ITEMS`. El path de caché y seed NO pasa por el clasificador (no se toca la capa de caché; sus ítems llevan `is_active_project = None`). La respuesta del clasificador es aditiva: un ítem cuyo `ProjectCard` omite un campo opcional conserva `None`.

### D6: Contrato aditivo en `schemas.py`

`ProjectItem` gana tres campos opcionales con default:
`is_active_project: bool | None = None`, `status_badge: Literal["Preventa","Entrega Inmediata","Agotado","Desconocido"] | None = None`, `price_from: str | None = None`.
El orden de `PreScrapeResponse` se preserva y gana un campo aditivo `meta: ScrapeMeta | None = None` con `filtered_out: int` (candidatos descartados por el LLM), poblado en el flujo `live` cuando hay descartes; el caso extremo responde `200 OK` con `items: []` y `meta.filtered_out = N`. `description_summary` se computa en el `ProjectCard` pero NO se expone en el API (se aprovechará en el change de UI). En el frontend, los tipos TS se amplían como opcionales en el mismo commit (no breaking, el modal ignora los campos nuevos hasta su rediseño).

### D7: Configuración

Nuevas variables en `Settings` (prefijo `ORBIT_` ya activo): `openrouter_api_key: str | None = None`, `llm_model: str = "deepseek/deepseek-v4-flash-0731:free"`, `llm_timeout: float = 8.0`, `llm_max_tokens: int = 4096`. Se documentan en `Backend/.env.example` (`ORBIT_OPENROUTER_API_KEY`, `ORBIT_LLM_MODEL`, `ORBIT_LLM_TIMEOUT`, `ORBIT_LLM_MAX_TOKENS`). El `base_url` default (`https://openrouter.ai/api/v1`) es constante del módulo; el modelo y la key SIEMPRE desde configuración → cero términos de proveedor hardcodeados en el dominio.

### D8: Golden dataset y evaluación

Se versiona `Backend/tests/fixtures/scraping/golden/` con 10 URLs reales (HTML congelado + `expected.json` con etiquetas `is_project` y precio esperado). Evaluación con mocks/respuestas grabadas opcional vía variable `ORBIT_LLM_EVAL_REAL=1`; por defecto la evaluación sólo corre con respuestas grabadas o stub para no consumir tokens en CI. Métricas: precisión `is_project` ≥ 90% y `price_from = None` cuando el HTML no contiene señal de precio (antialucinación).

## Risks / Trade-offs

- [Free-tier de OpenRouter con rate limits / inestabilidad del modelo `:free`] → Mitigación: fallback determinista (D4) y el modelo es configurable vía `ORBIT_LLM_MODEL`; la demo degrada a heurística, nunca a error.
- [Latencia del path `live` supera el P95 < 500ms del determinista] → Mitigación: la spec se acota en el delta — P95 < 500ms queda acotado a paths deterministas (cache/seed/LLM off o stub); con LLM el objetivo es no-bloqueo y P95 < 10s; el fallback responde < 500ms.
- [Structured output no garantizado en todos los modelos free] → Mitigación: `response_format` si está soportado + prompt estricto + parseo robusto + validación `ProjectCard` + fallback si no valida; los casos se cubren en el test de schema.
- [Coste si se llama por cada `live`] → 1 llamada por request (≤10 ítems), modelo ligero por defecto, cero tokens en tests (MockTransport), y la clasificación queda deshabilitada sin key.
- [Alucinación de precio] → en el prompt se fuerza `price_from = null` si no hay precio explícito; métrica de antialucinación sobre el golden dataset.
- [Fuga de la API key] → solo en entorno (`.env`), nunca en logs (ORB-NFR-005); se añade un test de grep/golden para verificar que no hay key en código o fixtures.

## Migration Plan

1. Añadir campos `ORBIT_LLM_*`/`ORBIT_OPENROUTER_API_KEY` a `Settings` y `.env.example`.
2. Implementar `llm.py`: `ProjectCard`, prompt y `LLMProjectClassifier` (httpx async, timeout, parseo robusto, validación).
3. Añadir `ORB-SCRAPE-006` (log-only) a `errors.py`.
4. Extender `schemas.py` con los campos aditivos de `ProjectItem` y `meta.filtered_out` en `PreScrapeResponse`.
5. Integrar el clasificador en `PreScraperService` (drop `is_project == false`, enriquecimiento, fallback) y wire en `create_app()` (`_default_pre_scraper`).
6. Golden dataset (fixtures) + tests: batch único, schema inválido, desalineación, timeout, fallback de red, sin key, mock OpenRouter, campos aditivos, cero ítems/`meta.filtered_out`, cache sin LLM.
7. Validar `openspec validate ai-scraping-classifier`, suite backend completa y arranque de `uvicorn`; verificación manual de una URL real con key.
8. **Rollback**: revertir el commit; es aditivo respecto al contrato y no toca caché ni ingestion, por lo que el revert restaura el comportamiento determinista completo.

## Open Questions

- Soporte de `response_format: json_object` en `deepseek/deepseek-v4-flash-0731:free`: **resuelto** — verificado en vivo (2026-09-17): devolvió JSON válido (`finish_reason=stop`, coste 0). El prompt instructivo y el parseo robusto se mantienen como defensa en profundidad (D2).
- ¿`description_summary` debe exponerse en el API en este change o solo en el rediseño de UI? (Propuesto: solo UI, ahora interno).
- ¿El free-tier es suficiente para la demo o se prefiere un modelo de pago barato por defecto? (`deepseek/deepseek-v4-flash-0731` paid está disponible; el fallback cubre el free si falla).
- Timeout estricto sin reintentos (D4): **resuelto** — una sola llamada, sin retries, para no degradar la latencia P95; la resiliencia la asume el fallback determinista.