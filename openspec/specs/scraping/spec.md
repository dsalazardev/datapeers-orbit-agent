# scraping Specification

## Purpose
TBD - created by archiving change add-scraping-module. Update Purpose after archive.
## Requirements
### Requirement: Pre-scrape de URL de entrada
El sistema SHALL exponer un endpoint `POST /api/v1/scraping/pre-scrape` que reciba una URL, ejecute una extracción superficial (shallow scraping) y devuelva una lista de proyectos detectados.

#### Scenario: Solicitud válida del pre-scrape
- **WHEN** el cliente envía `POST /api/v1/scraping/pre-scrape` con una URL válida
- **THEN** el sistema responde `200 OK` con un cuerpo JSON que contiene el listado de ítems detectados

#### Scenario: Solicitud con URL inválida
- **WHEN** el cliente envía una URL que no es http/https o está mal formada
- **THEN** el sistema responde un error `422 Unprocessable Entity` con detalle de validación

### Requirement: Límite de resultados del pre-scrape
El sistema SHALL devolver como máximo 10 proyectos por solicitud de pre-scrape.

#### Scenario: Más de 10 proyectos detectados
- **WHEN** la URL contiene más de 10 proyectos/enlaces relevantes
- **THEN** el sistema devuelve exactamente 10 ítems y no supera el límite

#### Scenario: Menos de 10 proyectos detectados
- **WHEN** la URL contiene 3 proyectos/enlaces relevantes
- **THEN** el sistema devuelve los 3 ítems detectados

### Requirement: Extracción superficial de proyectos

El sistema SHALL analizar la respuesta HTML de la URL mediante parseo rápido de etiquetas `<a>`, estructuras de tarjetas y metadatos, construyendo ítems con título y URL absoluta. El parseo SHALL ejecutarse en un thread pool vía `anyio` (fuera del event loop) y SHALL NOT realizarse más de una vez por solicitud sobre el mismo HTML.

#### Scenario: Detección de enlaces en la página

- **WHEN** el HTML contiene tags `<a href="...">` con texto legible
- **THEN** el sistema genera ítems de proyecto con el texto como título y la URL resuelta como enlace

#### Scenario: Parseo único por solicitud

- **WHEN** el pre-scrape procesa una URL
- **THEN** el HTML se parsea una sola vez y los distintos extractores comparten ese árbol, sin re-parseos duplicados

### Requirement: Respuesta de pre-scrape sin renderizado pesado
El sistema SHALL ejecutar el pre-scrape de forma síncrona, rápida y sin renderizado de JavaScript (shallow scraping).

#### Scenario: Tiempo de respuesta del pre-scrape
- **WHEN** el pre-scrape procesa una URL alcanzable
- **THEN** el sistema responde en la misma solicitud (síncrono) sin delegar a renderizado ni a un job asíncrono

### Requirement: Base para deep scraping posterior
El sistema SHALL incluir una estructura base para el procesamiento asíncrono y la sanitización de HTML, preparada para hacerse cargo en una fase posterior.

#### Scenario: Stub de sanitización de HTML
- **WHEN** se invoca el sanitizador con un fragmento HTML
- **THEN** el sistema aplica una limpieza básica (eliminación de scripts/etiquetas no deseadas) o devuelve una señal de no-implementado, sin romper el proceso

#### Scenario: Servicio desacoplado
- **WHEN** el módulo de scraping se integra en la app
- **THEN** cada responsable (router, schemas, servicios) vive en archivos separados dentro de `Backend/app/modules/scraping/`, sin acoplamiento a otros módulos

### Requirement: Selección de proyectos en el frontend
El sistema SHALL permitir al usuario ingresar una URL, decidir el pre-scrape y seleccionar hasta 10 proyectos detectados en un modal.

#### Scenario: Ingreso de URL y disparo del pre-scrape
- **WHEN** el usuario ingresa una URL en el formulario y la envía
- **THEN** el frontend invoca el endpoint de pre-scrape y muestra el listado de proyectos detectados en un modal

#### Scenario: Selección dentro del límite
- **WHEN** el usuario selecciona hasta 10 proyectos en el modal
- **THEN** el sistema permite confirmar la selección

#### Scenario: Superación del límite de selección
- **WHEN** el usuario intenta seleccionar más de 10 proyectos
- **THEN** el sistema bloquea la selección adicional e indica el límite alcanzado

### Requirement: Estados del cliente de pre-scrape
El sistema SHALL manejar en el frontend los estados de carga (loading), error y selección durante el pre-scrape.

#### Scenario: Carga en progreso
- **WHEN** el cliente del frontend está esperando la respuesta del pre-scrape
- **THEN** el sistema exhibe un estado de carga y deshabilita acciones duplicadas de envío

#### Scenario: Error del pre-scrape
- **WHEN** el pré-scrape falla (red, URL inválida, servidor)
- **THEN** el frontend muestra un mensaje de error y permite reintentar

### Requirement: Exclusión de contenedores de navegación en el pre-scrape
El sistema SHALL descartar todo candidato extraído de contenedores de navegación del DOM (`<nav>`, `<header>`, `<footer>`, `<aside>`/sidebars y menús) antes de construir ítems de proyecto.

#### Scenario: Enlace dentro de un contenedor de navegación
- **WHEN** un enlace candidato aparece dentro de `<nav>`, `<header>`, `<footer>` o `<aside>`
- **THEN** el sistema lo descarta y no genera un ítem de proyecto

#### Scenario: Enlace en el contenido principal
- **WHEN** un enlace candidato aparece fuera de los contenedores de navegación, en el contenido principal de la página
- **THEN** el sistema lo procesa con normalidad y genera el ítem si supera el resto de filtros

### Requirement: Filtro de palabras clave no relacionadas con proyectos
El sistema SHALL descartar candidatos cuyo texto o URL contenga palabras clave no relacionadas con proyectos inmobiliarios (p. ej. nosotros, aliados, contacto, blog, equipo, faq, login, registro, privacidad, términos), comparando sin distinguir mayúsculas/minúsculas y por segmento de palabra o de la ruta de la URL.

#### Scenario: Palabra clave negativa en el texto del enlace
- **WHEN** el texto visible de un enlace candidato contiene una palabra clave negativa (p. ej. "Contáctanos" o "Blog")
- **THEN** el sistema descarta el candidato

#### Scenario: Palabra clave negativa en la URL
- **WHEN** la URL de un candidato contiene una palabra clave negativa en su ruta (p. ej. `/blog/…`, `/nosotros`, `/contacto`)
- **THEN** el sistema descarta el candidato

#### Scenario: Candidato sin palabras clave negativas
- **WHEN** el texto y la URL de un candidato no contienen palabras clave negativas
- **THEN** el sistema mantiene el candidato como posible proyecto

### Requirement: Discriminación entre páginas agrupadoras y proyectos reales
El sistema SHALL diferenciar páginas agrupadoras, regionales o de índice (categorías, listados, ciudades, paginación) de proyectos individuales, y SHALL priorizar los proyectos concretos; los candidatos agrupadores se descartan cuando existan proyectos reales o se devuelven solo como último recurso.

#### Scenario: Enlace a una página agrupadora
- **WHEN** un candidato apunta a una página de agrupación/índice/regional (p. ej. `/proyectos/`, `/ciudad/manizales`, o con paginación `?page=`/`/pagina/`)
- **THEN** el sistema lo descarta o lo deja al final de la prioridad si no hay proyectos concretos disponibles

#### Scenario: Enlace a un proyecto concreto
- **WHEN** un candidato apunta a un proyecto individual identificable (URL específica de proyecto, título con nombre propio)
- **THEN** el sistema le asigna alta prioridad y lo incluye antes que cualquier candidato agrupador

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

### Requirement: Cero términos de cliente hardcodeados en el dominio

El sistema SHALL NOT contener términos, marcas o segmentos de URL propios de un cliente o prospecto concreto (p. ej. `somos-jyp`, `negocio-con-jyp`, `clientes-vis`) en el código de dominio del scraper. Todas las reglas de cliente SHALL vivir en configuración externa (`config.py` / variables `ORBIT_*`).

#### Scenario: Ausencia de términos de cliente en el dominio

- **WHEN** se busca en el código de dominio del scraper el término de un cliente específico (p. ej. `jyp`)
- **THEN** no existe ninguna coincidencia (grep `jyp` = 0)

#### Scenario: Reglas de cliente configurables

- **WHEN** se carga la configuración del scraper con reglas de cliente externas
- **THEN** el dominio consume esas reglas desde configuración y no desde constantes embebidas

### Requirement: Errores normalizados con reason_codes estables

El sistema SHALL responder todo error del endpoint de pre-scrape con un `reason_code` estable del conjunto `ORB-SCRAPE-XXX` y un mensaje seguro, y SHALL NOT exponer el texto crudo de la excepción al cliente (ORB-NFR-005).

#### Scenario: Fallo de red durante el pre-scrape

- **WHEN** el pre-scrape falla por red, timeout, WAF o URL inalcanzable
- **THEN** el sistema responde `502` con un `reason_code` estable (ORB-SCRAPE-XXX) y sin el texto de la excepción cruda

#### Scenario: Fallo de parseo durante el pre-scrape

- **WHEN** el parseo del HTML falla o produce un resultado inválido
- **THEN** el sistema responde un error normalizado con `reason_code` estable y sin texto crudo

#### Scenario: Cobertura completa de errores del router

- **WHEN** ocurre cualquier error manejado en el router de scraping
- **THEN** la respuesta incluye `reason_code` (100% de los errores normalizados)

### Requirement: Resiliencia en demo con caché local / seeded fallback

El sistema SHALL mantener un caché local (filesystem/JSON) de resultados de pre-scrape y SHALL disponer de un seeded fallback: cuando una URL no pueda obtenerse o el caché esté disponible, el sistema responde rápidamente desde caché o datos sembrados para no romper la demo.

#### Scenario: Hit de caché

- **WHEN** se solicita el pre-scrape de una URL ya cacheada
- **THEN** el sistema responde con los ítems desde caché sin red, en menos de 200ms

#### Scenario: Seeded fallback ante URL inalcanzable

- **WHEN** la URL no responde y no hay caché previa
- **THEN** el sistema responde en menos de 200ms usando el seeded fallback (datos sembrados), manteniendo la demo operativa

#### Scenario: Persistencia local del caché

- **WHEN** se completa un pre-scrape exitoso
- **THEN** el resultado se almacena en caché local (filesystem/JSON) para futuros hits

### Requirement: Fallo de red o URL inalcanzable

El sistema SHALL responder todo fallo de red o URL inalcanzable del pre-scrape con un `reason_code` estable (ORB-SCRAPE-XXX) mediante `502 Bad Gateway` (o equivalente de cliente/servidor), sin crashear y sin exponer el texto crudo de la excepción (ORB-NFR-005). Si existe caché local o seeded fallback disponible, el sistema SHALL preferir resolver la solicitud por esa vía en menos de 200ms.

Trazabilidad: ORB-NFR-005.

#### Scenario: Fallo de red o URL inalcanzable

- **WHEN** la URL no responde o falla la conexión
- **THEN** el sistema responde un error `502 Bad Gateway` con `reason_code` estable, sin texto crudo de la excepción

#### Scenario: Fallo de red con seeded fallback disponible

- **WHEN** la URL no responde y existe caché o seeded fallback
- **THEN** el sistema responde en menos de 200ms con los ítems del fallback en lugar del error crudo

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

