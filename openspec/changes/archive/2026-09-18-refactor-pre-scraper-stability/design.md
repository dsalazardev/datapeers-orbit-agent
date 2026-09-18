## Context

El módulo scraping vive en `Backend/app/modules/scraping/` con `router.py`, `schemas.py` y `services/pre_scraper.py` (582 líneas) más `services/sanitizer.py` (stub sin uso). `PreScraper` concentra fetch HTTP, parseo BeautifulSoup, poda del DOM, filtrado por keywords, clasificación de páginas agrupadoras y construcción de ítems. Problemas detectados:

- `BeautifulSoup` síncrono y CPU-bound corre dentro de `async def run()` (pre_scraper.py:308) y `_extract_from_navigation` re-parsea el HTML (pre_scraper.py:436), bloqueando el event loop de FastAPI.
- Términos de un cliente concreto (JYP: `somos-jyp`, `negocio-con-jyp`, `tu-negocio-con-jyp`, `clientes-vis`, `zona-clientes`) hardcodeados en `NEGATIVE_KEYWORDS`.
- `scraping/router.py` expone `detail=str(exc)` (texto crudo de la excepción) violando ORB-NFR-005, que ingestion sí cumple con `reason_code`.
- Singleton de módulo `_pre_scraper = PreScraper()` (router.py:8), inconsistente con el composition root de `create_app()`.

El cambio refactoriza para estabilidad y resiliencia en demos; la clasificación con LLM/batching, el rediseño del modal y el deep-scraping quedan fuera (P1).

## Goals / Non-Goals

**Goals:**
- Dejar el event loop libre: todo parseo CPU-bound corre en thread pool vía `anyio`.
- Cero términos de cliente hardcodeados en el dominio (grep `jyp` = 0); reglas externas en `config.py`.
- Errores del router 100% normalizados con `reason_codes` estables `ORB-SCRAPE-XXX`, sin texto crudo.
- Resiliencia en demo con caché local (JSON en disco) y seeded fallback (< 200ms).
- Desacople en submódulos con responsabilidad única y anotaciones de tipos completas.
- Suite de tests en verde incluyendo +4 tests de caché/reason_codes.

**Non-Goals:**
- Clasificación con LLM ni batching (difiere a P1).
- Rediseño del modal en el frontend.
- Deep scraping ni cambios en el módulo ingestion.
- Autenticación, rate limiting o persistencia distribuida del caché.

## Decisions

### D1: Estructura modular interna de `Backend/app/modules/scraping/`

Se reemplaza `services/pre_scraper.py` por una composición de submódulos con responsabilidad única dentro del paquete del módulo (se elimina la carpeta `services/`):

```
Backend/app/modules/scraping/
├── __init__.py
├── config.py        # Reglas de cliente externalizadas + límites del scraper
├── schemas.py       # PreScrapeRequest, ProjectItem, PreScrapeResponse (sin cambios)
├── parser.py        # Parseo/extracción puro: BeautifulSoup, atributos, domínio del scraper
├── cache.py         # Caché local filesystem/JSON + seeded fallback
├── errors.py        # Catálogo de reason_codes y DTO de error
└── router.py        # Capa HTTP: valida, delega, normaliza errores
```

- `config.py` expone dataclasses/config immutable con: `REQUEST_HEADERS`, `REQUEST_TIMEOUT`, `MAX_BODY_SIZE`, y las listas `NEGATIVE_KEYWORDS`, `INDEX_TERMS`, `REGIONAL_TERMS`, `REGIONAL_PREFIX_RE`, `WEAK_TITLES`, `PAGINATION_PARAMS`. Se eliminan los términos de cliente JYP y los duplicados de la lista.
- `parser.py` contiene la lógica pura (funciones puras o clase `HtmlParser`) sin I/O de red: `parse_html(html)`, `extract_candidates(soup, base_url, config)`, `_is_weak_title`, `_slug_title`, `_is_grouping_url`, etc. El dominio NO conoce clientes: recibe las reglas por parámetro desde `config`.
- `cache.py` implementa el puerto de caché (ver D3).
- `errors.py` define el catálogo de reason_codes (ver D4).
- `router.py` se vuelve una capa delgada: inyección de dependencias desde `create_app()` (ver D5).

**Alternativa descartada**: mantener `PreScraper` como clase única refactorizada. Se descarta porque el objetivo explícito es desacoplar en submódulos y que cada responsable tenga una sola razón de cambio.

**Por qué `scraping` usa un layout plano y no hexágono completo**: a diferencia de `ingestion` (que exige dominio puro, puertos y adaptadores sustituibles por contrato ORB-CON-015), el módulo `scraping` es pequeño y de flujo lineal — HTTP → parseo → DTO — sin infraestructura que sustituir ni caso de uso persistente. Tres capas de abstracción (domain/application/infrastructure con puertos) serían sobre-ingeniería aquí: `parser.py` ya es puro (sin I/O de red, recibe reglas por parámetro) y `config.py` externaliza las reglas de cliente, cubriendo los dos requisitos de testabilidad y desacople que importan con un solo nivel de paquete. Si el deep-scraping asíncrono (P1) madura el flujo con pipeline e infraestructura real, se adopta el patrón hexágono en ese momento, no antes.

**Normalización `grouping → link` (fuera de `parser.py`, en el orquestador)**: `parser.py` conserva la fuente semántica `"grouping"` en sus candidatos porque es información útil para la cascada y el fallback; sin embargo `PreScraperService` la normaliza a `"link"` antes de construir el DTO. La razón es doble: (1) `schemas.py` no se toca — `ProjectItem.source` sigue siendo `Literal["meta", "card", "link"]` (schemas.py:17) — y (2) el `pre_scraper.py` original sí construía `ProjectItem(source="grouping")` cuando `extract_candidates` devolvía la lista `grouping` de fallback, lo que provocaba un `ValidationError` de Pydantic latente. Normalizar en el borde mantiene el contrato público intacto y elimina ese bug sin ensuciar `schemas.py` ni el parser.

### D2: Patrón exacto de envoltorio con `anyio.to_thread.run_sync`

Todo el parseo CPU-bound se envuelve en `anyio.to_thread.run_sync` (sin crear un executor manual; `anyio` ya está disponible vía FastAPI/Starlette y respeta el límite de threads del event loop). No se usa `asyncio.to_thread` para mantener la compatibilidad con backends/utilities de `anyio` (ya en el árbol de dependencias) y su gestión de cancellation scope.

En el flujo async (`router` o un servicio `PreScraperService` que sigue existiendo como orquestador delgada):

```python
from anyio import to_thread
from bs4 import BeautifulSoup

async def _parse_html_async(self, html: bytes) -> BeautifulSoup:
    return await to_thread.run_sync(self._parse_html_sync, html)

def _parse_html_sync(self, html: bytes) -> BeautifulSoup:
    return BeautifulSoup(html[: self._config.max_body_size], "html.parser")
```

Para la función pura de extracción que recibe el `soup` (pura CPU en el árbol DOM):

```python
async def _extract_async(self, soup: BeautifulSoup, base_url: str) -> list[Candidate]:
    return await to_thread.run_sync(self._extract_sync, soup, base_url)

def _extract_sync(self, soup: BeautifulSoup, base_url: str) -> list[Candidate]:
    return extract_candidates(soup, base_url, self._config)
```

Reglas del patrón:

- **Solo el parseo y la extracción van al thread**: el fetch (`httpx.AsyncClient`) y la serialización de la respuesta permanecen `await` en el event loop.
- **Un único parseo y un único DOM por solicitud**: `parse_html` se llama una vez y todo el trabajo ocurre sobre el mismo árbol. La navegación se lee primero en sus propios buckets (con su propio `seen`), luego `_prune_navigation` poda el árbol **in situ** (sin `copy.copy`) y los extractores (meta → cards → links) corren sobre ese árbol ya podado; los candidatos de navegación se fusionan al final deduplicando contra `seen_urls` y respetando la precedencia meta > cards > links > navegación. Esto elimina tanto el segundo `BeautifulSoup(html)` de `_extract_from_navigation` como el clon estructural intermedio (`copy.copy`).
- **Orden**: `html = await _fetch(...)` (async) → `soup = await _parse_html_async(html)` (thread) → `candidates = await _extract_async(soup, url)` (thread) → construir `ProjectItem`s (puro, en el loop).
- **Error handling**: si el thread lanza (parseo malformado), la excepción se captura en el orquestador y se traduce a `ORB-SCRAPE-002` (ver D4). `to_thread.run_sync` propaga la excepción awaitable de forma estándar.

**Nota de rendimiento**: Python 3.14t (free-threaded) + la liberación del GIL hacen que el parseo en thread sea especialmente efectivo para concurrencia.

**Medición del test de concurrencia (50 pre-scrapes concurrentes, P95 de `GET /health`)**: la medición corre in-process con `httpx.ASGITransport(app=app)` (sin servidor `uvicorn` ni hilo de fondo), por lo que el P95 de `/health` mide directamente cuánto tarda el event loop en atender mientras el parseo está en vuelo; si el parseo bloqueara el loop, ese P95 subiría con él. En CPython 3.14t free-threaded (`PYTHON_GIL=0`) se mantiene muy por debajo del umbral (**~3.5 ms** medidos). Con el GIL activo el escenario degrada (~917 ms con 400 tarjetas y >5 s con 1500), por lo que el test se omite fuera de 3.14t con `skipif(sys._is_gil_enabled(), ...)`; la ejecución continua en CI queda fuera del alcance de este change.

### D3: Estructura y ubicación de la caché local (JSON) y seeded fallback

**Ubicación y formato**: directorio de datos de la app (configurable vía `ORBIT_SCRAPER_CACHE_DIR`, default `Backend/.cache/scraping/`):

```
.cache/scraping/
└── v1/
    ├── <sha256(url)>.json      # Un archivo por URL
    └── seed.json               # Paquete de datos sembrados (demos)
```

Cada `<sha256(url)>.json`:

```json
{
  "url": "https://example.com/path",
  "cached_at": "2026-09-17T12:00:00Z",
  "ttl_seconds": 3600,
  "items": [
    {"id": 1, "title": "Torres del Parque", "url": "https://example.com/proyectos/torres", "source": "card"}
  ],
  "truncated": false
}
```

**Flujo de la caché (orden de resolución)**:

1. **Cache hit** → si existe `<sha256>.json` y no expiró (`cached_at + ttl_seconds > now`), devolver los ítems desde disco sin red (< 200ms).
2. **Cache miss + fetch exitoso** → parsear, devolver y **persistir** el resultado en disco (escritura async fuera del hot path de respuesta, p. ej. `asyncio.create_task` o `to_thread` para el write).
3. **Cache miss + fetch fallido + seed disponible para esa URL** → devolver los ítems sembrados desde `seed.json` (< 200ms), marcando `truncated: true` y... sin mentir al operador: el log estructura `source=seed`.
4. **Sin caché ni seed** → error normalizado `ORB-SCRAPE-001` (fetch) o `ORB-SCRAPE-002` (parseo).

**Seed fallback**: `seed.json` es un mapa `url_key → {"items": [...]}` sembrado localmente (versionado en el repo para demos, no en `.env`). Se consigna como última línea de defensa para que la demo no se rompa con URLs reales caídas; el **log estructurado siempre registra** `cache_hit: bool` y `source: "cache"|"seed"|"live"`.

**Alternativa descartada**: caché en memoria (dict). Se descarta porque la resiliencia en demo debe sobrevivir reinicios del contenedor y porque `InMemoryOnboardingStateStore` de ingestion ya documenta la volatilidad como limitación; el filesystem JSON es simple y suficiente para el MVP. Redis queda para más adelante.

### D4: Catálogo de `reason_codes` `ORB-SCRAPE-XXX`

`errors.py` define un enum + un DTO de error usado por el router para todo 4xx/5xx del módulo:

```python
class ScrapeReasonCode(str, enum.Enum):
    FETCH_FAILED       = "ORB-SCRAPE-001"  # red/timeout/WAF/HTTP != 2xx
    PARSE_FAILED       = "ORB-SCRAPE-002"  # HTML malformado o extracción fallida
    INVALID_RESPONSE   = "ORB-SCRAPE-003"  # respuesta sin ítems válidos construibles
    UPSTREAM_BLOCKED   = "ORB-SCRAPE-004"  # 403/robots/WAF/CDN detectado (reservado)
    CACHE_UNAVAILABLE  = "ORB-SCRAPE-005"  # caché/seed inaccesible (reservado)
    INTERNAL_ERROR     = "ORB-SCRAPE-000"  # fallback genérico (500)
```

DTO de error normalizado (cuerpo de toda respuesta de error del router):

```json
{
  "error": {
    "reason_code": "ORB-SCRAPE-001",
    "message": "No se pudo cargar el sitio de origen.",
    "request_id": "84f2...",
    "http_status": 502
  }
}
```

Mapeo HTTP del router (4xx/5xx):

| reason_code | HTTP | Condición |
|---|---|---|
| `ORB-SCRAPE-001` | `502` | Fallo de red/timeout/URL inalcanzable (fetch) |
| `ORB-SCRAPE-002` | `502` | Parseo/extracción fallida |
| `ORB-SCRAPE-003` | `500` | Respuesta inválida (sin ítems construibles) |
| `ORB-SCRAPE-004` | `502` | Bloqueo upstream (reservado, futuro) |
| `ORB-SCRAPE-005` | `500` | Caché/seed inaccesible (reservado) |
| `ORB-SCRAPE-000` | `500` | Error no previsto (fallback, log con stack) |

Reglas de contratación (alineadas a ORB-NFR-005):
- `message` es un texto seguro, estático o parametrizado sólo con datos no sensibles (nunca `str(exc)`).
- El `request_id` del middleware de correlación de `main.py` se incorpora al DTO.
- `error.reason_code` SIEMPRE presente en cualquier error del router (métrica "100% con reason_code"). Los 4xx de validación Pydantic (`422`) quedan fuera del DTO (los genera FastAPI) y se aceptan como contrato existente.

### D5: Composición e inyección de dependencias

`create_app()` en `main.py` construye y expone el servicio de pre-scrape, eliminando el singleton de módulo:

```python
scraper_config = ScraperConfig.from_settings(settings)
scraper_cache = JsonFilePrefetchCache(cache_dir=settings.scraper_cache_dir, seed=load_seed())
app.state.pre_scraper = PreScraperService(config=scraper_config, cache=scraper_cache)
```

El router recibe el servicio desde `app.state` (o vía dependencia FastAPI). El contrato de éxito (`PreScrapeResponse`) no cambia.

## Risks / Trade-offs

- [Threads saturan el pool de `anyio` con muchos parsers pesados] → `to_thread.run_sync` usa el default que respeta el límite de threads por defecto de event loop; el límite de ítems (10) y `MAX_BODY_SIZE` acotan el trabajo; se mide con el test de 50 concurrentes.
- [Parseo free-threaded (3.14t) con bs4] → `beautifulsoup4` es compatible con free-threading (verificada en build actual); el thread pool además mitiga cualquier liberación parcial del GIL. El test de concurrencia (ASGITransport, in-process) mide P95 ~3.5 ms en 3.14t vs ~917 ms en 3.14 estándar (400 tarjetas), y se omite fuera de 3.14t con `skipif(sys._is_gil_enabled(), ...)`.
- [Caché en disco stale (resultado obsoleto)] → `ttl_seconds` por entrada + `cached_at`; hit expirado = miss y se re-consume.
- [Seed fallback enmascara URLs reales caídas en producción (no demo)] → el log estructurado registra `source=seed`; el seed vive en `seed.json` versionado y se documenta como exclusivo para demo; en producción puede deshabilitarse con `ORBIT_SCRAPER_SEED_ENABLED=false`.
- [Un único DOM cambia matices del fallback de navegación] → la navegación se lee antes de podar y se fusiona al final; se añadió un test de caracterización (`test_scraper_navigation_fallback.py`) que fija como *golden* el output exacto de la implementación previa (con `copy.copy`) para el fallback de navegación, el retorno de `grouping`, la precedencia body-sobre-nav y los duplicados intra-nav por selectores solapados, y se verificó byte-a-byte tras el refactor.
- [Eliminar `copy.copy` cambia el comportamiento observable] → mitigado por el test de caracterización anterior, que corre con `copy.copy` como golden antes del cambio y debe permanecer idéntico después (4 casos, `assert` por valor).
- [Cambio en el formato de error es BREAKING para el frontend] → el modal actual renderiza `detail`; se reemplaza por un mapeo `reason_code → mensaje` en el cliente dentro del mismo PR, se coordina el contrato en el mismo commit y se valida el build.

## Migration Plan

1. Crear `config.py`, `parser.py`, `cache.py`, `errors.py` y el orquestador `PreScraperService`; mover la lógica desde `services/pre_scraper.py` sin cambiar el contrato de éxito.
2. Eliminar `services/` (incluida `sanitizer.py`, que era código muerto) y actualizar imports de `router.py` y `main.py`.
3. Aplicar `anyio.to_thread.run_sync` al parseo/extracción y el parseo único.
4. Externalizar reglas y límites a `config.py` + `Settings` (`ORBIT_SCRAPER_TIMEOUT`, `ORBIT_SCRAPER_MAX_BODY_SIZE`, `ORBIT_SCRAPER_CACHE_DIR`, `ORBIT_SCRAPER_SEED_ENABLED`) y documentarlas en `Backend/.env.example`.
5. Implementar caché JSON + seeded fallback y el contrato de `reason_codes` en el router.
6. Añadir los +4 tests (caché, reason_codes, concurrencia, grep jyp=0) y ajustar `test_api_contract.py` / `test_scraping_regression.py`.
7. Validar `openspec validate`, build backend, suite completa, `docker compose up --build`.
8. **Rollback**: revertir el commit del cambio; es aditivo respecto al contrato de éxito y no toca ingestion. La única ruptura es el formato de error, que se coordina con el frontend.

## Open Questions

- ¿El frontend necesita el `request_id`/`reason_code` para mensajes más finos, o basta con el `message` seguro? (afecta al DTO, no al backend).
- ¿`seed.json` se genera manualmente por capacidad o debe poblarse con un script de siembra? (para la demo).
- ¿El `ttl_seconds` de la caché debe ser configurable por entorno? (default propuesto 3600).