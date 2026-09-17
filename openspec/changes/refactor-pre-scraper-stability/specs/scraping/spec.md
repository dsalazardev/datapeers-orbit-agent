# scraping Specification (delta)

## Priorities

- (priority: medium) Parseo sin bloqueo del event loop
- (priority: medium) Cero términos de cliente hardcodeados en el dominio
- (priority: medium) Errores normalizados con reason_codes
- (priority: low) Resiliencia en demo con caché local / seeded fallback

## ADDED Requirements

### Requirement: Parseo sin bloqueo del event loop

El sistema SHALL ejecutar todo el parseo CPU-bound del HTML (BeautifulSoup y derivados) en un thread pool vía `anyio`, de forma que un pre-scrape en curso NO bloquee otras solicitudes concurrentes del event loop de FastAPI.

#### Scenario: Pre-scrapes concurrentes sin degradación

- **WHEN** se envían 50 solicitudes de pre-scrape concurrentes sobre URLs alcanzables
- **THEN** el event loop permanece libre y la latencia P95 se mantiene por debajo de 500ms

#### Scenario: Parseo aislado del fetch

- **WHEN** se ejecuta el pre-scrape de una URL
- **THEN** la descarga de red (await) y el parseo del HTML corren en contextos separados, sin parseos sincrónicos dentro de la corrutina

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

## MODIFIED Requirements

### Requirement: Fallo de red o URL inalcanzable

El sistema SHALL responder todo fallo de red o URL inalcanzable del pre-scrape con un `reason_code` estable (ORB-SCRAPE-XXX) mediante `502 Bad Gateway` (o equivalente de cliente/servidor), sin crashear y sin exponer el texto crudo de la excepción (ORB-NFR-005). Si existe caché local o seeded fallback disponible, el sistema SHALL preferir resolver la solicitud por esa vía en menos de 200ms.

Trazabilidad: ORB-NFR-005.

#### Scenario: Fallo de red o URL inalcanzable

- **WHEN** la URL no responde o falla la conexión
- **THEN** el sistema responde un error `502 Bad Gateway` con `reason_code` estable, sin texto crudo de la excepción

#### Scenario: Fallo de red con seeded fallback disponible

- **WHEN** la URL no responde y existe caché o seeded fallback
- **THEN** el sistema responde en menos de 200ms con los ítems del fallback en lugar del error crudo

### Requirement: Extracción superficial de proyectos

El sistema SHALL analizar la respuesta HTML de la URL mediante parseo rápido de etiquetas `<a>`, estructuras de tarjetas y metadatos, construyendo ítems con título y URL absoluta. El parseo SHALL ejecutarse en un thread pool vía `anyio` (fuera del event loop) y SHALL NOT realizarse más de una vez por solicitud sobre el mismo HTML.

#### Scenario: Detección de enlaces en la página

- **WHEN** el HTML contiene tags `<a href="...">` con texto legible
- **THEN** el sistema genera ítems de proyecto con el texto como título y la URL resuelta como enlace

#### Scenario: Parseo único por solicitud

- **WHEN** el pre-scrape procesa una URL
- **THEN** el HTML se parsea una sola vez y los distintos extractores comparten ese árbol, sin re-parseos duplicados