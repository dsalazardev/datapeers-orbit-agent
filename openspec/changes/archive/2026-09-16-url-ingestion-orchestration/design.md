## Context

El estado actual y la motivación están en `proposal.md` - Why. Puntos del código que condicionan el diseño (verificados el 16-sep-2026):

- Backend FastAPI con un único módulo `Backend/app/modules/scraping/` (router, schemas, services) sin capas de dominio ni puertos; `Backend/app/main.py` declara la app a nivel de módulo y registra el router de scraping con prefijo `/api/v1` (no existe fábrica de aplicación ni inyección de dependencias).
- No hay configuración por entorno, logging, middleware, CORS ni pruebas automatizadas (solo `Backend/test_main.http`).
- Restricciones del entorno de desarrollo: Python local 3.14.7 **con GIL**; el Dockerfile instala 3.14t free-threaded (`PYTHON_GIL=0`) — no se modifica en este cambio. El venv local está **desincronizado** respecto a `pyproject.toml`/`uv.lock` (faltan `httpx` y `beautifulsoup4`): la primera verificación exige `uv sync`. El `TestClient` de starlette **no está disponible** en este entorno porque exige el paquete `httpx2` (ausente); `httpx` 0.28.1 sí está en el lock.
- El pre-scraper acepta un cliente `httpx` inyectable (`Backend/app/modules/scraping/services/pre_scraper.py:284`), lo que permite una prueba de regresión sin red.
- Convenciones del repositorio: artefactos OpenSpec en español con encabezados en inglés, código y nombres en inglés, conventional commits, rama `feature/url-ingestion-orchestration`.

## Goals / Non-Goals

**Goals:**

- Punto de entrada `POST /api/v1/onboardings` con validación real del destino de red (no solo de forma).
- Arranque del pipeline en segundo plano sin bloquear la respuesta, con registro del arranque.
- Estado del onboarding consultable con vía primaria (`url_scraping`) y secundarias (`pdf`, `brochure`).
- Arquitectura hexagonal mínima y real: dominio puro, casos de uso y puertos, adaptadores sustituibles.
- Configuración por entorno y logging estructurado auditables, sin secretos.
- Pruebas derivadas de los criterios de aceptación, con evidencia ejecutable.

**Non-Goals (límites de diseño):**

- Sin fetch/scraping de la URL ni paralelización multihilo (ORB-TK-02/03): aquí solo se valida y se arranca.
- Sin base de datos ni base vectorial: el adaptador de estado es en memoria y volátil (ORB-INT-006 pendiente).
- Sin autenticación, cuentas ni multi-tenant: el "prospecto con cuenta creada" se representa con `onboarding_id` y la brecha se declara.
- Sin límite de tasa (diferido, ver D15), sin CORS (el consumo previsto es vía proxy nginx del frontend, mismo origen) y sin UI.
- Sin ingesta de PDF/Excel/JSON: solo se declaran como vías secundarias del estado.

## Decisions

### D1: Módulo feature-first con capas hexagonales dentro de `modules/ingestion/`

Estructura:

```
Backend/app/modules/ingestion/
  domain/            # dataclasses, enums, reglas puras de validación
  application/       # puertos, caso de uso, runner esqueleto
  infrastructure/    # settings, logging, resolver DNS, almacén en memoria, scheduler
  router.py          # adaptador HTTP (delgado, sin lógica de negocio)
  schemas.py         # contratos Pydantic de entrada/salida
```

Razón: coherencia con el módulo `scraping` existente y dirección de dependencias hacia dentro (infraestructura → aplicación → dominio). Alternativas: capas globales `app/domain|application|infrastructure` (mejor para compartir estado entre tareas futuras, pero introduce una segunda convención y un refactor mayor ahora); módulo plano al estilo `scraping` (descartado: no cumple ORB-CON-003/ORB-CON-015/ORB-NFR-008).

### D2: API `POST /api/v1/onboardings` (202) + `GET /api/v1/onboardings/{id}`

El recurso con estado es el onboarding; el POST lo crea y arranca la ingesta. La cuenta del criterio de aceptación se representa con `onboarding_id` generado en servidor y la brecha se declara (no se inventa autenticación). Alternativa descartada: `/ingestions` (el estado exigido por el criterio es "del onboarding").

### D3: Configuración con `pydantic-settings`

Variables: `ORBIT_APP_ENV` (default `local`) y `ORBIT_LOG_LEVEL` (default `INFO`); precedencia entorno > `.env` > defaults; `.env.example` versionado sin secretos (ORB-NFR-005). El timeout de resolución DNS (5 s) queda como constante documentada del adaptador, no como variable, para no ampliar la superficie de configuración sin necesidad. Alternativa descartada: `os.environ` + parser propio (más código, sin validación tipada). `pydantic-settings` es pura Python: sin extensión compilada, sin riesgo de ABI 3.14/GIL ↔ 3.14t.

### D4: Segundo plano con `BackgroundTasks`

El caso de uso programa el trabajo a través de un puerto; el adaptador concreto usa `BackgroundTasks` de FastAPI, que ejecuta después de emitir la respuesta. Alternativas: `asyncio.create_task` (descartada: ciclo de vida no gestionado y no integrado con el ciclo de la respuesta); colas/brokers/workers (prohibidos por el alcance; la paralelización es ORB-TK-03).

### D5: Cuatro puertos, caso de uso dependiente solo de abstracciones

- `OnboardingStateStore`: `save(state)`, `get(onboarding_id)`.
- `IngestionPipeline`: `run(onboarding_id)` (ejecución del pipeline; esqueleto en esta tarea).
- `IngestionScheduler`: `schedule(job)`.
- `HostResolver`: `resolve(host) -> direcciones`.

El router resuelve el caso de uso desde el estado de la app; el composition root vive en `create_app()`. El programador es una dependencia por llamada (`handle(url, request_id, scheduler)`) porque el adaptador `BackgroundTasks` es de alcance de petición, y `create_app()` acepta una fábrica de programador sustituible para las pruebas. Razón: permite probar el no bloqueo con dobles (D11) y sustituir adaptadores sin tocar dominio ni casos de uso (ORB-CON-015).

### D6: Modelo de dominio y estados

`OnboardingState` (dataclass pura, sin Pydantic en dominio): `onboarding_id` (UUID4 generado en servidor), `source_url`, `primary_route = url_scraping`, `secondary_routes = (pdf, brochure)`, `status ∈ {received, ingestion_started, failed}`, `created_at`/`updated_at` en UTC. `request_id` se toma de la cabecera `X-Request-ID` o se genera, y se propaga a logs y a la cabecera de la respuesta. Alternativa descartada: Pydantic en el dominio (acopla el núcleo a la librería de validación HTTP).

### D7: Validación de destino: reglas puras en dominio + `HostResolver` en infraestructura

Reglas puras (sin red): URL analizable y con host; esquema `http`/`https`; sin credenciales embebidas; host no local (`localhost`, `*.localhost`, `*.local`, `*.internal`, `*.home.arpa`); IP literal verificada contra rangos bloqueados (privados, loopback, link-local, no especificadas, multicast, reservadas y metadatos de nube, con desempaquetado de IPv4-mapeada-en-IPv6). Infraestructura: `socket.getaddrinfo` ejecutado en hilo (`anyio.to_thread`) con timeout detectado vía `cancel_scope.cancelled_caught`; el timeout y una resolución sin direcciones se traducen a `dns_resolution_failed` (nunca a `address_not_allowed`), y **todas** las direcciones resultantes se verifican con la misma regla pura. Códigos de motivo estables: `url_malformed`, `scheme_not_allowed`, `credentials_not_allowed`, `host_not_allowed`, `address_not_allowed`, `dns_resolution_failed`. El **seam de revalidación antes de la petición** (resolver y revalidar justo antes de cada fetch saliente) queda documentado para ORB-TK-02; en esta capacidad no hay petición saliente. Alternativa descartada: validar solo con `HttpUrl` de Pydantic (no bloquea destinos internos ni resuelve DNS).

### D8: Errores HTTP con motivos seguros

`422` con cuerpo `{"detail": {"reason_code": ..., "message": ...}}` y mensaje estable en inglés; `404` para onboarding inexistente; `202` para aceptación. Nunca se devuelve el texto crudo de la excepción (se registra en el log). Alternativa descartada: `400` (menos consistente con la validación ya usada por FastAPI).

### D9: Logging estructurado con la stdlib

`logging` de la biblioteca estándar con formatter JSON mínimo (sin dependencias nuevas), configurado en `create_app` según settings; `request_id` en un `contextvar` fijado por middleware; eventos del arranque y de la validación con `request_id`, `onboarding_id` (cuando exista) y `reason_code` (cuando aplique). Alternativa descartada: `structlog` (dependencia nueva no justificada).

### D10: Dominio con dataclasses; Pydantic solo en los bordes

Los schemas HTTP y la configuración usan Pydantic; el dominio y los casos de uso, no. Alternativa descartada: Pydantic en todo (rompe la pureza del dominio que exige ORB-CON-003).

### D11: Estrategia de prueba del no bloqueo en tres niveles (aprobada)

- **N1 — unitaria**: schedulador falso que registra el trabajo **sin ejecutarlo**; el caso de uso debe retornar sin invocar `pipeline.run` (prueba causal, sin red ni ASGI). Verifica ORB-FR-023 (arranque sin bloquear).
- **N2 — contrato por ASGI**: `202` + estado inicial `received` con vía primaria y secundarias; `422` por cada clase de rechazo con su `reason_code`; `404` de consulta inexistente; transición a `ingestion_started` tras el trabajo. Verifica los dos criterios Gherkin de ORB-TK-01 y ORB-FR-004/005/INT-004.
- **N3 — evidencia fuerte (latencia real)**: servidor uvicorn real en puerto efímero con un pipeline bloqueado por un evento; se mide la latencia del POST y se verifica causalmente que respondió **mientras el trabajo sigue bloqueado**; después se libera el evento y se comprueba la transición a `ingestion_started`. Verifica ORB-NFR-017 (experiencia sin espera) sin umbrales frágiles.

Cada prueba cita en su docstring el criterio Gherkin o el ID ORB-* que verifica. Alternativa descartada: depender de medidas de tiempo con umbral fijo (frágil en CI/local).

### D12: Cliente de pruebas HTTP: `httpx.ASGITransport`

Las pruebas de contrato usan `httpx.AsyncClient` con `ASGITransport` sobre la app creada con `create_app(...)` y dobles inyectados. El `TestClient` de starlette queda descartado en este entorno porque exige `httpx2`, que no está instalado (verificado); añadir `httpx2` solo para pruebas no se justifica, y probar únicamente el caso de uso sin ASGI no verificaría los códigos y payloads del criterio. `anyio` ya está en el lock: las pruebas asíncronas usan `@pytest.mark.anyio` con el fixture `anyio_backend` en `asyncio`, sin `pytest-asyncio`.

### D13: Idempotencia: sin deduplicación por URL

Cada `POST` crea un onboarding nuevo con identificador propio, aunque repita URL. Razón: sin autenticación no hay identidad de prospecto y deduplicar por URL conflataría leads distintos de la misma constructora, rompiendo el embudo por lead (PostHog en ORB-FR-015). Riesgo aceptado en MVP: el doble clic/reintento genera trabajo duplicado. Alternativas: deduplicación por URL activa (descartada por lo anterior); `Idempotency-Key` por cliente (decisión abierta, no implementada).

### D14: Límite de tasa diferido

Sin límite de tasa en esta tarea: sin identidad ni persistencia, un limitador en memoria no es duradero ni efectivo con múltiples procesos, y excede el alcance. El riesgo de abuso queda declarado en la spec con la validación de destino repetida en cada admisión; el límite (o una regla en el borde) debe preceder al fetch real saliente de ORB-TK-02. Alternativa descartada: limitador en memoria (falsa sensación de protección).

### D15: Sincronización del entorno antes de verificar

La primera acción de la fase de implementación es `uv sync` en `Backend` (el venv local no coincide con el lock: faltan `httpx` y `beautifulsoup4`), con evidencia de importación de `app.main` y arranque real. No se cambian dependencias para compensar la desincronización.

## Risks / Trade-offs

- [Adaptador de estado en memoria: pierde datos al reiniciar y no sirve con varios workers] → Límite declarado en la spec y comentario de deuda (ORB-INT-006); supuesto de un solo worker en el MVP; adaptador definitivo pendiente de ratificación con datapeers.
- [Endpoint público sin autenticación] → Riesgo de abuso declarado en la spec; validación en cada admisión; límite de tasa diferido (D14) que debe preceder a ORB-TK-02; despliegue solo en staging (ORB-CON-002).
- [DNS TOCTOU / rebinding: la validación resuelve en admisión, pero un fetch futuro podría resolver otra IP] → Seam de revalidación documentado para ORB-TK-02 (resolver y revalidar inmediatamente antes de cada petición saliente con la misma regla); en esta capacidad no hay fetch.
- [Duplicados por URL: dos onboardings para el mismo sitio] → Aceptado (D13); `Idempotency-Key` como decisión abierta; coste bajo mientras no exista fetch.
- [Resolución DNS lenta o colgada] → Timeout de 5 s en el adaptador (`anyio.move_on_after`) y mapeo a `dns_resolution_failed` (422); un fallo transitorio es reintentable por el cliente.
- [Nueva dependencia `pydantic-settings`] → Pura Python; sin wheels compiladas; justificada aquí y sincronizada con `uv.lock`.
- [Refactor de `Backend/app/main.py` a `create_app()`] → Compatible: se conserva `app = create_app()` para `uvicorn app.main:app` y las rutas del pre-scrape; prueba de regresión con `httpx.MockTransport` sobre el pre-scraper (cliente inyectable, `pre_scraper.py:284`).
- [Sin pruebas en el repositorio] → `pytest` entra como dependencia de desarrollo y las pruebas citan criterio/ORB para trazabilidad (ORB-FR-019, ORB-NFR-015).

## Migration Plan

1. **Sincronizar entorno**: `uv sync` en `Backend`; evidenciar importación de `app.main` y arranque de uvicorn (sin cambiar dependencias).
2. Añadir `pydantic-settings` (runtime) y `pytest` (desarrollo); regenerar `uv.lock`.
3. Crear el módulo `ingestion` (dominio → puertos → caso de uso → adaptadores) y refactorizar `main.py` a `create_app()` con `app = create_app()`.
4. Crear `Backend/.env.example` con `ORBIT_APP_ENV` y `ORBIT_LOG_LEVEL` (sin valores secretos).
5. Escribir las pruebas (dominio, contrato ASGI, no bloqueo N1–N3, regresión del pre-scrape) citando criterio/ORB.
6. Verificar: `pytest` con salida real, petición manual contra un sitio público y contra una URL interna prohibida, repositorio limpio y sin secretos.
- **Rollback**: revertir el commit; el cambio es aditivo y no altera rutas ni comportamiento del pre-scrape existente.

## Open Questions

- Modelo de cuentas/autenticación: el MVP opera con `onboarding_id`; a validar con datapeers (Andrés). No cambia specs ni tareas de este cambio.
- Idempotencia por cliente (`Idempotency-Key`): extensión futura no implementada (D13).
- Ubicación del límite de tasa (borde/ingress vs aplicación) antes del fetch real de ORB-TK-02 (D14).
- Adaptador definitivo de estado (Postgres/pgvector, ORB-INT-006): pendiente de ratificación con datapeers.
- CORS: innecesario mientras el consumo sea vía proxy nginx (mismo origen); reevaluar si aparecen llamadas directas del navegador.
