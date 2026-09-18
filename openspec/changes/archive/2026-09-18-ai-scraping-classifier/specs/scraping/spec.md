# scraping Specification (delta)

## Priorities

- (priority: high) Clasificación semántica híbrida de proyectos con LLM
- (priority: high) Fallback determinista sin error ante fallo del LLM
- (priority: medium) Latencia y no-bloqueo de la clasificación LLM
- (priority: medium) Parseo sin bloqueo del event loop (alcance aclarado con LLM)

## ADDED Requirements

### Requirement: Clasificación semántica híbrida de proyectos con LLM

El sistema SHALL, cuando esté configurada una API key de OpenRouter (`ORBIT_OPENROUTER_API_KEY`), clasificar semánticamente los candidatos detectados por el extracción determinista en el flujo `live`, mediante UNA sola llamada batch al proveedor LLM por solicitud, exigiendo structured output JSON validado contra el esquema estricto `ProjectCard` (`is_project`, `is_active_project`, `title`, `description_summary`, `price_from`, `status_badge`, `score`). Los ítems con `is_project == false` se descartan antes de la respuesta final, y los ítems conservados se enriquecen con los campos aditivos de `ProjectItem`. Cuando la clasificación descarta candidatos, la respuesta SHALL incluir `meta.filtered_out = N`; si los descarta todos, el sistema SHALL responder `200 OK` con `items: []` y `meta.filtered_out = N`, sin generar un error.

#### Scenario: Batch único por solicitud

- **WHEN** el pre-scrape de flujo `live` detecta hasta 10 candidatos
- **THEN** el cliente LLM realiza una única llamada que clasifica todos los candidatos, nunca una llamada por candidato

#### Scenario: Validación estricta contra ProjectCard

- **WHEN** la respuesta del LLM no valida contra el esquema Pydantic `ProjectCard` (JSON malformado o campos fuera de contrato)
- **THEN** el sistema descarta la respuesta del LLM y aplica el fallback determinista, sin propagar el contenido crudo

#### Scenario: Desalineación del batch

- **WHEN** la respuesta del LLM no se alinea 1:1 con los candidatos (longitud distinta o índices rotos)
- **THEN** el sistema trata la respuesta como no válida y aplica el fallback determinista completo

#### Scenario: Descarte total con meta.filtered_out

- **WHEN** el LLM clasifica todos los candidatos como `is_project == false`
- **THEN** el sistema responde `200 OK` con `items: []` y `meta.filtered_out = N`, sin generar un error

#### Scenario: Descarte de no-proyectos

- **WHEN** un ítem clasificado tiene `is_project == false`
- **THEN** el sistema lo excluye de la respuesta final

#### Scenario: Campos aditivos preservando el contrato existente

- **WHEN** la clasificación LLM tiene éxito para un ítem
- **THEN** `ProjectItem` incluye `is_active_project`, `status_badge` y `price_from`, y SHALL NOT alterar los campos existentes `title`, `url` y `source`

#### Scenario: Precisión sobre el golden dataset

- **WHEN** se evalúa la clasificación sobre el golden dataset (10 URLs reales con HTML guardado)
- **THEN** la precisión de `is_project` es ≥ 90% y `price_from` es `None` cuando el HTML no contiene precio (cero alucinaciones de precio)

### Requirement: Fallback determinista sin error ante fallo del LLM

El sistema SHALL NOT fallar la solicitud cuando el LLM no esté disponible: sin API key configurada, timeout de 8s agotado, o error de red/HTTP, el resultado usa la extracción determinista con `is_active_project = None` (no verificado), el log estructurado registra `source=fallback`, y el usuario nunca recibe un error 500 causado por el LLM ni texto crudo de la excepción (ORB-NFR-005).

#### Scenario: Sin API key configurada

- **WHEN** `ORBIT_OPENROUTER_API_KEY` no está definida
- **THEN** el sistema responde `200 OK` con los ítems deterministas y `is_active_project = None`, sin error 500 y sin invocar al LLM

#### Scenario: Timeout de la llamada LLM

- **WHEN** el LLM no responde dentro del timeout duro de 8s
- **THEN** el sistema aplica el fallback determinista y el log registra `source=fallback` con un `reason_code` estable (ORB-SCRAPE-006, log-only)

#### Scenario: Error de red o HTTP del proveedor

- **WHEN** la llamada a OpenRouter falla por red, 4xx/5xx o respuesta inválida
- **THEN** el sistema aplica el fallback determinista sin exponer el texto crudo (ORB-NFR-005) y sin devolver error 500 al cliente

#### Scenario: Cero llamadas reales en la suite de tests

- **WHEN** se ejecuta la suite de tests
- **THEN** no se realizan llamadas reales a OpenRouter (mocks/`httpx.MockTransport`), garantizando cero consumo de tokens

### Requirement: Latencia y no-bloqueo de la clasificación LLM

El sistema SHALL ejecutar la llamada al LLM como I/O asíncrona (`await` sobre `httpx.AsyncClient`) sin bloquear el event loop, con timeout duro configurable (default 8s). Los paths deterministas (cache hit, seeded fallback y flujo `live` con LLM deshabilitado) SHALL NOT invocar al LLM y SHALL mantener su latencia acordada (< 200ms cache/seed; P95 < 500ms determinista).

#### Scenario: Cache/seed sin invocar al LLM

- **WHEN** se resuelve por cache hit o seeded fallback
- **THEN** el sistema no invoca al LLM y responde en menos de 200ms

#### Scenario: Latencia del fallback

- **WHEN** el LLM no está disponible y se aplica el fallback determinista
- **THEN** el endpoint responde en menos de 500ms

#### Scenario: Event loop libre durante la clasificación LLM

- **WHEN** se envían 50 pre-scrapes `live` concurrentes con clasificación LLM (proveedor mock/stub)
- **THEN** el event loop permanece libre: la llamada al LLM es `await` (I/O asíncrono) y no introduce operaciones CPU-bound síncronas

## MODIFIED Requirements

### Requirement: Parseo sin bloqueo del event loop

El sistema SHALL ejecutar todo el parseo CPU-bound del HTML (BeautifulSoup y derivados) en un thread pool vía `anyio`, de forma que un pre-scrape en curso NO bloquee otras solicitudes concurrentes del event loop de FastAPI. La métrica P95 < 500ms se mide en paths deterministas (cache/seed, LLM deshabilitado o proveedor stub); en el path `live` con LLM real la clasificación se mide por no-bloqueo del event loop (I/O `await`), no por ese umbral.

#### Scenario: Pre-scrapes concurrentes sin degradación

- **WHEN** se envían 50 solicitudes de pre-scrape concurrentes sobre URLs alcanzables en paths deterministas (LLM deshabilitado o stub)
- **THEN** el event loop permanece libre y la latencia P95 se mantiene por debajo de 500ms

#### Scenario: Parseo aislado del fetch

- **WHEN** se ejecuta el pre-scrape de una URL
- **THEN** la descarga de red (await) y el parseo del HTML corren en contextos separados, sin parseos sincrónicos dentro de la corrutina

#### Scenario: Event loop libre tras añadir la llamada LLM

- **WHEN** 50 pre-scrapes `live` concurrentes incluyen la clasificación LLM (con proveedor mock)
- **THEN** el event loop permanece libre: el parseo corre en thread pool vía `anyio` y la llamada LLM es `await` de I/O, sin CPU-bound en la corrutina