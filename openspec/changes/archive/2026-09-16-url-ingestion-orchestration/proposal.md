## Why

El MVP de ORBIT («Pruébame Ahora») exige que un prospecto entregue la URL de su sitio y que el sistema inicie la ingesta automáticamente, sin formularios ni cargas manuales (ORB-FR-002, ORB-FR-005, ORB-INT-004). Hoy el repositorio solo tiene el pre-scrape shallow y su UI: no existe un punto de entrada que valide el destino, ni un arranque no bloqueante del pipeline, ni un estado del onboarding consultable, ni configuración por entorno, ni logging auditable (ORB-NFR-015). La historia ORB-TK-01 abre la Épica 1 del Sprint 1 y desbloquea el scraping detallado de las tareas siguientes (ORB-TK-02/03, ORB-FR-023).

## What Changes

- **Nuevo módulo backend `ingestion`** con arquitectura hexagonal mínima y real: dominio puro (dataclasses, sin dependencias de framework), casos de uso y puertos en la capa de aplicación, adaptadores concretos en infraestructura (ORB-CON-015, ORB-NFR-008, ORB-CON-003).
- **Endpoint de entrada** `POST /api/v1/onboardings`: valida la URL destino e inicia la ingesta en segundo plano, respondiendo sin esperar a que el trabajo termine (ORB-FR-023, ORB-NFR-017).
- **Validación de destino obligatoria**: solo esquemas `http`/`https`, sin credenciales embebidas, bloqueo de rangos privados/loopback/link-local, direcciones de metadatos de nube y nombres de host locales; resolución DNS y verificación de todas las IPs resultantes. En esta tarea no hay petición saliente: el seam de revalidación antes de la petición queda documentado para ORB-TK-02.
- **Estado del onboarding consultable** con `GET /api/v1/onboardings/{id}`: registra desde el arranque la vía primaria (`url_scraping`) y las vías secundarias (`pdf`, `brochure`) (ORB-FR-004, ORB-FR-005, ORB-INT-004).
- **Puertos y adaptadores**: `OnboardingStateStore` (adaptador en memoria, provisional y volátil; el definitivo depende de ORB-INT-006, pendiente de ratificación con datapeers), `IngestionPipeline` (esqueleto que registra el inicio; el trabajo real pertenece a ORB-TK-02/03), `IngestionScheduler` (adaptador sobre BackgroundTasks) y `HostResolver` (resolución DNS en infraestructura).
- **Configuración por entorno y logging estructurado**: `pydantic-settings`, nuevo `Backend/.env.example` (sin secretos, ORB-NFR-005) y logging JSON con identificadores de solicitud y de onboarding (ORB-NFR-015, ORB-FR-019).
- **Pruebas automatizadas (nuevas)**: `pytest` como dependencia de desarrollo; pruebas de dominio, de contrato por ASGI con `httpx.ASGITransport` (el `TestClient` de starlette no está disponible en este entorno) y de no bloqueo en tres niveles. No se añade `pytest-asyncio`: se usa la integración de `anyio`, ya presente.
- **No se modifica** el módulo `scraping` ni su spec; se añade una prueba de regresión del pre-scrape (ORB-FR-021).

## Capabilities

### New Capabilities
- `ingestion`: punto de entrada y validación de la URL del sitio, arranque no bloqueante del pipeline de ingesta y estado del onboarding con sus vías de ingesta (primaria URL; secundarias PDF/brochure), todo a través de puertos y adaptadores desacoplados.

### Modified Capabilities
<!-- Sin cambios de requisitos: la spec `scraping` conserva sus requisitos y escenarios intactos. -->

## Impact

- **Backend**: nuevo paquete `Backend/app/modules/ingestion/` (dominio, aplicación, infraestructura, router y schemas) y registro del router en `Backend/app/main.py`; configuración y logging inicializados en el arranque de la app. Sin cambios en `Backend/app/modules/scraping/`.
- **API**: nuevos `POST /api/v1/onboardings` (202 Accepted) y `GET /api/v1/onboardings/{id}` (200/404). El endpoint existente `POST /api/v1/scraping/pre-scrape` no cambia.
- **Dependencias**: `pydantic-settings` (runtime, pura Python) y `pytest` (desarrollo). Sin dependencias compiladas nuevas, sin `httpx2` y sin base de datos.
- **Configuración**: nuevo `Backend/.env.example`; `.gitignore` y `.dockerignore` ya contemplan `.env`.
- **Fuera de alcance (explícito)**: scraping detallado y paralelización multihilo (ORB-TK-02/03), RAG/embeddings/base vectorial (ORB-TK-04, ORB-INT-006), mapeo al esquema de datapeers (ORB-TK-07), ingesta de PDF/Excel/JSON (aquí solo se declaran como vías secundarias), frontend, autenticación/cuentas y multi-tenant. La «cuenta creada» del criterio de aceptación se representa con un `onboarding_id` y la brecha se declara en el design.
