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
- Recall `is_project` ≥ 80%, Precision ≥ 85%, F1 ≥ 0.80 sobre un golden dataset representativo (≥ 10 URLs positivas reales y ≥ 10 negativas, 135 candidatos, 14 sitios). Cero alucinaciones de `price_from`.

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

La llamada incluye los ≤10 candidatos (`title`, `url`, `source`) en un único `user` message con índices 1..N y exige una respuesta JSON estructurada alineada a esos índices. Razones: (1) minimiza latencia y coste (1 round-trip), (2) el límite natural de 10 ítems hace innecesaria la segmentación en múltiples llamadas, y (3) simplifica el fallback (todo o nada). La petición usa `response_format: {"type": "json_object"}`, cuyo soporte fue **verificado en vivo** (2026-09-17) sobre `deepseek/deepseek-v4-flash-0731:free`: devolvió `finish_reason=stop` y JSON válido con coste 0.

**Contrato de respuesta — dos formatos aceptados (verificado 2026-09-18).** El parseo normaliza ambas formas a una lista ordenada 1..N antes de validar y alinear:

1. **Objeto indexado (forma real de `json_object`)**: `{"1": {…}, "2": {…}, …}`, una clave por candidato en orden. Es lo que devuelve el modelo free con `response_format=json_object` (el fixture `raw_openrouter_response.json` es el string exacto capturado en vivo). **Procedencia del espacio inicial**: el fixture empieza con un espacio en blanco antes del `{`; se verificó en vivo (2026-09-18) con una llamada directa httpx a OpenRouter que `repr(content)[0:100] == ' {"ok":true}…'`, confirmando que el espacio es emitido por el modelo, no un artefacto de captura de PowerShell. El parser lo tolera (`content.strip()` en `_extract_json_payload`).
2. **Array plano (defensa en profundidad)**: `[{…}, {…}, …]`, para modelos/proveedores que ignoren el shape indexado o devuelvan un top-level array.

El cliente exige `len(respuesta) == len(candidatos)` tras normalizar; si no alinea, si el objeto indexado no cubre 1..N o si algún elemento no valida contra `ProjectCard` → fallback completo (D4). El test de contrato 6.13 fija ambos formatos a partir de payloads reales.

**Normalización de títulos (comportamiento deseado, verificado 2026-09-18).** El modelo reformatea los títulos de los candidatos, removiendo el texto de marketing que el HTML concatena (precios "Desde $...", "Unidades desde...", descripciones de ventas — como en las tarjetas de fincaraiz) y quedándose con el nombre legible del proyecto (p. ej. "Mirador del parque", "Bau 69"). Esto es un beneficio: los títulos llegan limpios al frontend. Como consecuencia, los títulos grabados en `recorded_responses.json` pueden diferir de los candidatos originales en `expected.json`, por lo que `_align_cards` y la evaluación golden (D8) alinean **por índice** (orden 1..N exigido por el prompt), nunca por título.

### D3: Cliente HTTP y no-bloqueo

Se usa `httpx.AsyncClient` dedicado (independiente del client de fetch del servicio) apuntando a `{base_url}/chat/completions` con headers `Authorization: Bearer {api_key}`. Toda la llamada es `await` de I/O en el event loop — sin `parse HTML` CPU-bound, por lo que NO se usa `to_thread`. El client NO reintenta: una sola llamada estricta; la resiliencia recae en el fallback determinista (D4) para no degradar la latencia P95. Un único `AsyncClient` se construye en el wiring y se cierra en el lifespan de la app; alternativa aceptada en tests: inyección de transporte (`httpx.MockTransport`) para cero llamadas reales.

**Doble capa de timeout.** El límite de 8s (`ORBIT_LLM_TIMEOUT`) se aplica en dos niveles complementarios:

1. **Timeout httpx por operación** (`timeout=self._timeout` en el client): acota connect/read-y-write por hueco. Necesario, pero **insuficiente**: el temporizador de lectura se reinicia con cada fragmento, así que un proveedor que envía la respuesta "a gotas" mantiene la conexión viva indefinidamente (verificado en vivo 2026-09-18: con `timeout=8s` una respuesta a gotas tardó 47s).
2. **Cota dura de reloj de pared con `anyio.fail_after(self._timeout)`** envolviendo `client.post(...)`: garantiza que la llamada completa se aborta al cumplirse los 8s, sin importar el patrón de entrega del proveedor. Al cancelarse, se cierra el stream/respuesta (el `finally` del stream libera el recurso) y el `TimeoutError` se traduce a fallback. Es la capa que hace efectivo el "timeout estricto" del contrato (D4).

La combinación evita que un free-tier lento bloquee el endpoint decenas de segundos; sin la capa (2), el `timeout` de httpx no acota el caso patológico. El test 6.4 (stall total) y el test slow-drip (entrega fraccionada) cubren ambas capas.

### D4: Fallback determinista y logging

Reglas de decisión, en orden:
1. Sin `api_key` configurada → no se instancia client real; flujo `live` devuelve ítems deterministas con `is_active_project = None`, sin invocar el LLM.
2. Llamada OK → validación `ProjectCard` OK y alineación 1:1 (`len(respuesta) == len(candidatos)` con índices alineados) → enriquecer ítems, descartar `is_project == false` y reportar los descartes en `meta.filtered_out`.
3. Timeout estricto (8s, sin reintentos), error de red, HTTP no-2xx, JSON/schema inválido o desalineación del batch → ítems deterministas con `is_active_project = None` (y `status_badge`/`price_from` en `None`), log estructurado con `evt=llm_classification_fallback`, `source=fallback` y `reason_code=ORB-SCRAPE-006`. El timeout se implementa como **cota dura de reloj de pared** con `anyio.fail_after(timeout)` alrededor de la llamada: verificado en vivo (2026-09-18) que el `timeout` de httpx NO acota llamadas cuya respuesta llega a gotas (el temporizador de lectura se reinicia por fragmento) — con proveedor lento y `timeout=8s`, httpx tardó 47s; con `anyio.fail_after`, la llamada se aborta a los 8s y cae al fallback. Sin esta cota, un proveedor free-tier lento bloquearía el endpoint decenas de segundos.
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

Se versiona `Backend/tests/fixtures/scraping/golden/` con 14 URLs reales (HTML congelado + `expected.json` con etiquetas `is_project` y precio esperado). Las URLs incluyen sites de múltiples dominios (construccionesmarval, conconcreto, camacol, metrocuadrado, pisos, fincaraiz, sancarlos, elcampo, inmobiliaria, portafolio) con listados de fincaraiz que aportan ≥ 10 tarjetas de proyectos reales (departamentos, casas, oficinas en desarrollo, apartaestudios, lotes urbanizables) como positivos y ≥ 10 meta/paginación/navegación como negativos.

Evaluación con mocks/respuestas grabadas opcional vía variable `ORBIT_LLM_EVAL_REAL=1`; por defecto la evaluación corre con respuestas grabadas o stub para no consumir tokens en CI. **La grabación del golden usó `timeout=180s` con reintentos para registrar el output completo del modelo en cada sitio nuevo, incluso ante la volatilidad del free-tier (picos de 40-90s); es un tiempo de captura off-line, NO el comportamiento de producción** — en producción rige la cota dura de 8s (D3/D4). Las respuestas grabadas para sitios 11-14 se obtuvieron con timeout 180s y reintentos ante volatilidad del free-tier; los títulos de las respuestas LLM pueden acortarse respecto al candidato original, por lo que la métrica alinea por índice (orden 1..N) y no por título. Métricas de cierre (clase positiva): Recall ≥ 80%, Precision ≥ 85%, F1 ≥ 0.80 y `price_from = None` cuando el HTML no contiene señal de precio (antialucinación).

## Risks / Trade-offs

- [Free-tier de OpenRouter con rate limits / inestabilidad del modelo `:free`] → Mitigación: fallback determinista (D4) y el modelo es configurable vía `ORBIT_LLM_MODEL`; la demo degrada a heurística, nunca a error.
- [Latencia del path `live` supera el P95 < 500ms del determinista] → Mitigación: la spec se acota en el delta — P95 < 500ms queda acotado a paths deterministas (cache/seed/LLM off o stub); con LLM el objetivo es no-bloqueo y P95 < 10s; el fallback responde < 500ms.
- [Proveedor lento que envía la respuesta a gotas: el timeout de httpx se reinicia por fragmento y la llamada podría durar > 8s] → Mitigación: cota dura de reloj de pared con `anyio.fail_after(8s)` envolviendo el `post` (D3), que aborta y libera el stream aunque los bytes sigan llegando; cubierto por el test slow-drip (entrega fraccionada cada 0.5s) además del test de stall total. Se acepta el trade-off de que una respuesta legítimamente lenta se descarta al cumplir 8s y cae al fallback determinista en vez de esperar.
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