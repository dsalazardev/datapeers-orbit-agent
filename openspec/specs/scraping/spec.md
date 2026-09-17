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
El sistema SHALL analizar la respuesta HTML de la URL mediante parseo rápido de etiquetas `<a>`, estructuras de tarjetas y metadatos, construyendo ítems con título y URL absoluta.

#### Scenario: Detección de enlaces en la página
- **WHEN** el HTML contiene tags `<a href="...">` con texto legible
- **THEN** el sistema genera ítems de proyecto con el texto como título y la URL resuelta como enlace

#### Scenario: Enlaces relativos
- **WHEN** un enlace usa una ruta relativa
- **THEN** el sistema la resuelve contra la URL base de la página y devuelve una URL absoluta

#### Scenario: Fallo de red o URL inalcanzable
- **WHEN** la URL no responde o falla la conexión
- **THEN** el sistema responde un error `502 Bad Gateway` (o equivalente de cliente/servidor) indicando el fallo, sin crashear

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

