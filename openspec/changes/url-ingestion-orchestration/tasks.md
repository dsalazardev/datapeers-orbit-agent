## 1. Entorno y dependencias

- [ ] 1.1 Crear la rama `feature/url-ingestion-orchestration` desde el HEAD actual de `feature/scraping-module` (contiene el pre-scraper finalizado) y verificar con `git branch --show-current`. No tocar `main`.
- [ ] 1.2 Ejecutar `uv sync` en `Backend` y demostrar con evidencia que `uv run python -c "import app.main"` funciona y que uvicorn arranca (el venv está desincronizado; NO cambiar dependencias para compensar). [D15]
- [ ] 1.3 Añadir `pydantic-settings` (runtime) y `pytest` (desarrollo) con `uv add` y confirmar que `uv.lock` se actualiza sin wheels compiladas nuevas. [D3, D12]

## 2. Dominio (puro, sin framework)

- [ ] 2.1 Crear `Backend/app/modules/ingestion/domain/models.py` con `OnboardingState` (dataclass), enums de estado (`received`, `ingestion_started`, `failed`) y de vías (`url_scraping`, `pdf`, `brochure`); verificar con prueba unitaria que el módulo se importa sin FastAPI ni Pydantic. [spec: Estado del onboarding…, ORB-FR-004, ORB-FR-005, ORB-INT-004]
- [ ] 2.2 Crear `Backend/app/modules/ingestion/domain/validation.py` con las reglas puras (URL malformada, esquema, credenciales, hosts locales, IP literal bloqueada y desempaquetado IPv4-mapeada) con `reason_code` estable; verificar con prueba de tabla cada clase de rechazo y la aceptación pública. [spec: Entrada de URL y validación…, ORB-FR-002, ORB-FR-005]

## 3. Aplicación (puertos y casos de uso)

- [ ] 3.1 Definir los cuatro puertos en `Backend/app/modules/ingestion/application/ports.py` (`OnboardingStateStore`, `IngestionPipeline`, `IngestionScheduler`, `HostResolver`) y verificar que no importan infraestructura ni FastAPI. [spec: Puertos y adaptadores…, ORB-CON-015, ORB-NFR-008]
- [ ] 3.2 Implementar `StartUrlIngestion` en `Backend/app/modules/ingestion/application/use_cases.py` (validar → resolver → verificar direcciones → guardar estado → programar trabajo) y verificar con la prueba unitaria N1 (schedulador falso que no ejecuta) que retorna sin invocar el pipeline. [spec: Arranque no bloqueante…, ORB-FR-023, D11-N1]
- [ ] 3.3 Implementar el runner esqueleto (`Backend/app/modules/ingestion/application/runner.py`) que registra el inicio, transiciona a `ingestion_started` y marca `failed` ante excepción; verificar con pruebas unitarias de transición y de fallo. [spec: Arranque no bloqueante…, ORB-FR-023]

## 4. Infraestructura (adaptadores)

- [ ] 4.1 Crear `Backend/app/modules/ingestion/infrastructure/settings.py` con `pydantic-settings` (`ORBIT_APP_ENV`, `ORBIT_LOG_LEVEL`) y defaults; verificar con pruebas de defaults y de override por variable de entorno. [spec: Configuración por entorno…, ORB-NFR-005]
- [ ] 4.2 Crear `Backend/app/modules/ingestion/infrastructure/logging.py` (formatter JSON + `contextvar` de `request_id`); verificar con `caplog` que los registros de arranque y de validación incluyen `request_id`, `onboarding_id` y `reason_code`, sin secretos. [spec: Configuración por entorno…, ORB-NFR-015, ORB-FR-019]
- [ ] 4.3 Crear `Backend/app/modules/ingestion/infrastructure/resolver.py` (`getaddrinfo` en hilo con `anyio.to_thread` y timeout de 5 s; el timeout se detecta con `cancel_scope.cancelled_caught` y tanto el timeout como la resolución sin direcciones se traducen a `dns_resolution_failed`, nunca a `address_not_allowed`); verificar con pruebas unitarias de resolvedor colgado (timeout), resolvedor que devuelve vacío y resolución real en la verificación manual. [spec: Entrada de URL y validación…, D7]
- [ ] 4.4 Crear `Backend/app/modules/ingestion/infrastructure/store.py` (en memoria) con comentario de deuda ORB-INT-006; verificar con prueba unitaria que otro doble del mismo puerto sustituye al adaptador sin tocar dominio ni caso de uso. [spec: Puertos y adaptadores…, ORB-INT-006]
- [ ] 4.5 Crear `Backend/app/modules/ingestion/infrastructure/scheduler.py` sobre `BackgroundTasks`; verificar en la prueba de contrato que el trabajo se ejecuta tras la respuesta y el estado termina en `ingestion_started`. [spec: Arranque no bloqueante…, D4]

## 5. HTTP y composición

- [ ] 5.1 Crear `Backend/app/modules/ingestion/schemas.py` y `Backend/app/modules/ingestion/router.py` (`POST /api/v1/onboardings` → 202; `GET /api/v1/onboardings/{id}` → 200/404; errores 422 con `reason_code` seguro); verificar con pruebas de contrato ASGI (N2) de aceptación, cada rechazo y 404. [spec: Entrada…/Estado…, D8, D12]
- [ ] 5.2 Refactorizar `Backend/app/main.py` a `create_app()` + `app = create_app()` con middleware de `request_id`, logging y registro de routers; verificar arranque real de uvicorn y que la spec y el endpoint de `scraping` siguen intactos. [D12, riesgo de refactor]

## 6. Configuración del repositorio

- [ ] 6.1 Crear `Backend/.env.example` con `ORBIT_APP_ENV` y `ORBIT_LOG_LEVEL` y comentario explicativo; verificar que no contiene secretos y que `.gitignore`/`.dockerignore` ya lo contemplan. [spec: Configuración por entorno…, ORB-NFR-005]

## 7. Pruebas

- [ ] 7.1 Pruebas de dominio (tabla de rechazos + aceptación) citando en cada docstring el criterio 1 de ORB-TK-01 y su ORB-*; verificar que pasan. [criterio Gherkin 1]
- [ ] 7.2 Pruebas de contrato ASGI con `httpx.ASGITransport` (202 + estado inicial con vía primaria/secundarias; 422 por clase; 404) citando los criterios 1 y 2; verificar que pasan. [criterios Gherkin 1 y 2, D11-N2]
- [ ] 7.3 Prueba unitaria de no bloqueo N1 (schedulador falso) citando ORB-FR-023; verificar que el caso de uso retorna sin ejecutar `pipeline.run`. [D11-N1]
- [ ] 7.4 Prueba de evidencia fuerte N3: uvicorn real en puerto efímero, pipeline bloqueado por evento, medición de latencia del POST; verificar causalmente que responde con el trabajo aún bloqueado y que después transiciona a `ingestion_started`. Si el entorno lo impide, declararlo sin ocultarlo. [ORB-NFR-017, D11-N3]
- [ ] 7.5 Prueba de regresión del pre-scrape con `httpx.MockTransport` inyectado (el servicio acepta `client` en `Backend/app/modules/scraping/services/pre_scraper.py:284`) citando ORB-FR-021; verificar 200 y tope de 10 sin red real. [spec `scraping`, no romper lo existente]

## 8. Verificación final y evidencia

- [ ] 8.1 Ejecutar `uv run pytest -v` completo y pegar la salida real; declarar cualquier fallo sin ocultarlo. [criterios de éxito de ORB-TK-01]
- [ ] 8.2 Verificación manual: `POST` con URL pública real (202 + estado), `POST` con URL interna prohibida (422 con motivo) y `GET` del estado; pegar ambas respuestas reales. [criterios Gherkin 1 y 2]
- [ ] 8.3 Comprobar repositorio limpio y sin secretos (`git status`, revisión de `.env.example`) y registrar la tabla de trazabilidad requisito ORB-* → spec → código → prueba. [ORB-FR-019, ORB-NFR-015]
