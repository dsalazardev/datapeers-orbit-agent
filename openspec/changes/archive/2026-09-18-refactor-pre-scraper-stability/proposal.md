## Why

El `pre_scraper.py` (582 líneas) es un god-object que bloquea el event loop de FastAPI (BeautifulSoup síncrono dentro de `async def`), tiene términos hardcodeados de un cliente (JYP) y expone excepciones crudas en el router violando ORB-NFR-005.

## What Changes

- Desacoplar `pre_scraper.py` en submódulos.
- Ejecutar el parseo en thread pool (anyio).
- Extraer reglas de cliente a `config.py`.
- Normalizar respuestas con `reason_codes` (ORB-SCRAPE-XXX).
- Añadir estrategia de caché local / seeded fallback para resiliencia en demos.

## Invariantes Positivas

- Parsing CPU-bound corre en thread pool vía anyio (event loop libre).
- Cero términos de cliente hardcodeados en el código de dominio.
- Errores del router normalizados a `reason_codes` estables.
- Funcionamiento resiliente en demo mediante cache hit / seeded fallback.

## Non-Goals

- NO se integra clasificación con LLM ni batching en este change (eso va en P1).
- NO se rediseña el modal en el frontend.
- NO se implementa deep scraping ni se toca ingestion.

## Métricas de éxito

- 0 hardcodeos de cliente en `/domain/` (grep "jyp" = 0).
- Event loop libre: 50 requests concurrentes sin degradación (P95 < 500ms).
- 100% de errores del router con `reason_code`.
- Seeded fallback responde en < 200ms.
- Suite de tests en verde (+4 tests para cache/reason_codes).

## Capabilities

### New Capabilities
- Ninguna: el refactor no introduce una capacidad nueva.

### Modified Capabilities
- `scraping`: cambian los requisitos de no-bloqueo del event loop (parseo en thread pool), la configuración de reglas de cliente (cero hardcodeos), el contrato de errores (`reason_codes` estables ORB-SCRAPE-XXX sin texto crudo) y la resiliencia en demo (caché local / seeded fallback).

## Impact

- **Código afectado**: `Backend/app/modules/scraping/services/pre_scraper.py` (desacople en submódulos), nuevo `config.py` de reglas de cliente, nuevo manejo de errores con `reason_codes`, capa de caché local (filesystem/JSON), `Backend/app/modules/scraping/router.py` (respuestas normalizadas), `Backend/app/main.py` (wiring).
- **API**: el cuerpo de éxito de `POST /api/v1/scraping/pre-scrape` no cambia; el formato de error cambia a `reason_code` estable. Es **BREAKING** para el frontend (el modal actual renderiza `detail`); se coordina en el mismo commit añadiendo un mapeo `reason_code → mensaje` en el cliente.
- **Dependencias**: ninguna nueva, se reutiliza `anyio` y `httpx` (ya presentes).
- **Restricciones técnicas**: FastAPI + Python 3.14 con arquitectura hexagonal; caché local filesystem/JSON.
- **Tests**: se amplía `Backend/tests/` con +4 tests para caché/reason_codes.