## Why

El pre-scraper determinista (`parser.py`) alcanzó su límite: cada regla nueva para distinguir "proyecto" de "blog" o "precio" de "cuota" arregla un sitio y rompe otro. Los falsos positivos llegan a la demo y el usuario no ve estado, precio ni descripción, solo títulos. Necesitamos validación semántica que el determinismo no puede dar.

## What Changes

- Configurar OpenRouter como proveedor LLM (variables `ORBIT_OPENROUTER_API_KEY`, `ORBIT_LLM_MODEL`).
- Nuevo cliente asíncrono en `app/modules/scraping/llm.py` que envía candidatos en UNA sola llamada batch a OpenRouter y exige structured output JSON.
- Esquema Pydantic estricto `ProjectCard` para la respuesta del LLM:
  `is_project: bool`, `is_active_project: bool`, `title: str`, `description_summary: str | None`, `price_from: str | None`, `status_badge: Literal["Preventa","Entrega Inmediata","Agotado","Desconocido"]`, `score: int`.
- Integrar el filtro LLM en `PreScraperService` entre la extracción determinista y la respuesta final: descartar `is_project == False`.
- Si el LLM descarta todos los candidatos, el endpoint responde `200 OK` con `items: []` y `meta.filtered_out: N` (sin error).
- Fallback: si no hay API key, timeout (8s) estricto sin reintentos, error de red/HTTP, schema inválido o desalineación del batch → devolver candidatos deterministas con `is_active_project = None` (no verificado), log `source=fallback`.
- Tests con mocks de OpenRouter (sin consumir tokens reales).

## Invariantes Positivas

- El cliente LLM hace UNA llamada por request, no una por candidato.
- La respuesta del LLM valida contra `ProjectCard` (Pydantic); si no valida, se descarta y se aplica fallback.
- Timeout duro de 8s por llamada al LLM.
- Sin API key configurada → fallback silencioso, sin error 500 al usuario.
- El contrato de éxito de `POST /pre-scrape` cambia SOLO añadiendo campos a `ProjectItem` (`is_active_project`, `status_badge`, `price_from`) y un `meta` aditivo en la respuesta (`filtered_out`); los campos existentes (`title`, `url`, `source`) se preservan.
- Cero llamadas reales a OpenRouter en la suite de tests.

## Non-Goals

- NO se migra a RAG, vector DB ni embeddings.
- NO se hace deep scraping de fichas de proyecto.
- NO se rediseña el frontend (Tailwind y Cards van en change separado).
- NO se toca ingestion ni la capa de caché.
- NO se introducen nuevos modelos por encima de un peso "ligero" (≤ ~10B o flash-tier).

## Métricas de éxito

- Precisión de `is_project` ≥ 90% sobre golden dataset (10 URLs reales con HTML guardado).
- Latencia P95 del endpoint con LLM < 10s; con fallback < 500ms.
- Cero alucinaciones de `price_from` sobre golden dataset (si el HTML no tiene precio, `price_from = None`).
- Suite verde: tests existentes + ≥ 6 nuevos (batch, schema, timeout, fallback, sin key, mock OpenRouter).

## Capabilities

### New Capabilities
- Ninguna: la clasificación es una mejora aditiva sobre la capacidad `scraping` existente.

### Modified Capabilities
- `scraping`: cambian los requisitos de extracción de proyectos (validación semántica híbrida determinista + LLM) y el contrato de éxito de `POST /pre-scrape` (campos aditivos `is_active_project`, `status_badge`, `price_from` y descarte de no-proyectos).

## Impact

- **Código afectado**: nuevo `Backend/app/modules/scraping/llm.py` (cliente LLM + `ProjectCard`), `Backend/app/modules/scraping/service.py` (filtro LLM entre extracción y respuesta + fallback), `Backend/app/modules/scraping/schemas.py` (campos aditivos de `ProjectItem`), `Backend/app/core/settings.py` + `Backend/.env.example` (nuevas variables `ORBIT_*`), `Backend/app/main.py` (wiring del cliente LLM en `_default_pre_scraper`).
- **API**: el contrato de éxito de `POST /api/v1/scraping/pre-scrape` es **aditivo** (no breaking): se añaden `is_active_project`, `status_badge`, `price_from` a `ProjectItem` y `meta: {filtered_out}` a la respuesta; `title`, `url`, `source` se preservan. El formato de error (`reason_code`) no cambia.
- **Dependencias**: ninguna nueva. Se reutilizan `httpx` (cliente async), `anyio` y `pydantic` ya presentes. SDK oficial de OpenRouter solo si es estable; en caso contrario, `httpx` directo — reutiliza `httpx.MockTransport` para tests (sin coste de tokens).
- **Restricciones técnicas**: FastAPI + Python 3.14t (free-threaded), arquitectura del módulo scraping ya refactorizada (P0); modelo por defecto disponible en OpenRouter (verificado: `deepseek/deepseek-v4-flash-0731:free` existe en `https://openrouter.ai/api/v1/models`).
- **Tests**: se amplía `Backend/tests/` con +6 tests (batch único, validación de schema, timeout, fallback, sin key, mock OpenRouter) y un golden dataset de 10 URLs con HTML guardado para las métricas de precisión.