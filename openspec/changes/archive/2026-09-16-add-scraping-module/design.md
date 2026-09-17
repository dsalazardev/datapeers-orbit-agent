## Context

ORBIT es un monorepo con backend FastAPI (`Backend/`) y frontend React + Vite + TS (`Frontend/`), orquestados por docker-compose (backend en `:8000`, frontend en `:80` con nginx que hace proxy de `/api/` → `backend:8000`). Actualmente el backend está en `Backend/main.py` con endpoints de demo y el frontend es el template por defecto de Vite. No hay ninguna capacidad de extracción de datos, y `openspec/specs/` está vacío.

Este cambio introduce la capacidad `scraping` siguiendo una arquitectura modular feature-driven, con dos fases: pre-scraping shallow (síncrono) y base para deep-scraping (asíncrono + sanitización).

## Goals / Non-Goals

**Goals:**
- Proveer un endpoint `POST /api/v1/scraping/pre-scrape` que devuelva hasta 10 proyectos detectados de forma síncrona.
- Estructura modular en backend (`Backend/app/modules/scraping/`) con router, schemas y servicios desacoplados.
- Estructura modular en frontend (`Frontend/src/features/scraping/`) con tipos, cliente HTTP, componentes y hook.
- Base lista para deep-scraping asíncrono y sanitización de HTML.

**Non-Goals:**
- Deep scraping completo asíncrono (fase de producción posterior).
- Renderizado de JavaScript (headless browser) para el pre-scrape.
- Persistencia de datos o colas de jobs.
- Autenticación/authorización.
- Tests automatizados como parte de este cambio (se deja la estructura sin capa de pruebas).

## Decisions

### D1: Reubicar la app FastAPI a `Backend/app/main.py`
El backend pasa de un archivo raíz a un paquete `app/` con subcarpetas por módulo. Esto habilita la arquitectura modular y la registración de routers por feature.
- **Alternativa**: mantener `main.py` en la raíz e importar los módulos desde `app/`. Se descarta para evitar imports hacia arriba del paquete.

### D2: Dependencias nuevas: `httpx` + `beautifulsoup4`
`httpx` se usa para el fetch asíncrono de la página y `beautifulsoup4` para el parseo rápido de HTML (shallow scraping). Ambos se agregan a `pyproject.toml` y se sincronizan con `uv` (regenerando `uv.lock`).
- **Alternativa**: `requests` + `lxml`. `requests` es síncrono y no integra bien con el async de FastAPI sin escalar en threads; `httpx` ofrece API async nativa. `lxml` es más veloz que bs4 pero más pesado de instalar; para un pre-scrape se prioriza simplicidad.
- **Nota**: el runtime del contenedor es Python 3.14t (free-threaded); `beautifulsoup4` es lint-agnostic y compatible.

### D3: Schemas Pydantic `PreScrapeRequest`, `ProjectItem`, `PreScrapeResponse`
`PreScrapeRequest` valida la URL y el límite (`max_items` con default 10, clamp 1–10). `ProjectItem` modela cada proyecto detectado (id, título, url absoluta, fuente). `PreScrapeResponse` envuelve la lista.
- **Alternativa**: validar la URL manualmente en el router. Se descarta: el router debe delegar validación a schemas para mantener la capa HTTP limpia.

### D4: Servicio `pre_scraper.py` con estrategia de extracción en cascada
El servicio intenta, en orden: (1) metadatos/OpenGraph rápidos, (2) estructuras de tarjetas, (3) tags `<a>` con texto legible. Resuelve enlaces relativos contra la URL base y respeta el límite de 10.
- **Alternativa**: un solo path de extracción (solo `<a>`). En cascada se obtiene mejor señal sin coste significativo.

### D5: Stub `sanitizer.py`
Sanitizador con función `sanitize_html` que aplica limpieza básica (remover `<script>`, `<style>` y atributos `on*`) o lanza/no-op controlado. Es la base del deep-scraping; queda invocable pero no en el hot path del pre-scrape.
- **Alternativa**: omitir el stub. El usuario lo exige explícitamente como requisito estructural (Fase 2 - Base).

### D6: Estructura feature en frontend dentro de `features/scraping/`
`types/scraping.types.ts`, `services/scrapingApi.ts`, `components/UrlInputForm.tsx`, `components/PreScrapeModal.tsx`, `hooks/usePreScrape.ts`. `App.tsx` orquesta el flujo: formulario → respuesta → modal → selección.
- **Alternativa**: componentes sueltos en `src/components` con llamadas inline. Se descarta: el feature-folder encapsula el módulo y facilita su reutilización/aislamiento.

### D7: Delegación del envío al modal
El hook `usePreScrape` dispara la llamada, y `PreScrapeModal` recibe los items detectados y gestiona el estado de selección (máximo 10) de forma local, emitiendo la confirmación hacia `App`.
- **Alternativa**: gestionar selección en `App`. Se descarta para aislar la lógica del modal.

### D8: Docker
No se requieren cambios en `docker-compose.yml`. El `Dockerfile` del backend debe apuntar el comando de arranque a `app.main:app` (ajuste menor). La comunicación frontend→backend sigue por el proxy de nginx ya existente.
- **Alternativa**: exponer el backend directamente al browser. Se descarta: se mantiene el `location /api/` actual.

### D9: Cabeceras de navegador y filtro de enlaces (fix WAF/CDN)
Durante la verificación con `https://constructoraberlin.com/` (Hostinger CDN) el endpoint devolvía `502 Bad Gateway`: el fetch de `httpx` recibía `403 Forbidden` porque el WAF del sitio rechaza el header set "plano" de httpx (solo `User-Agent: python-httpx`, `Accept: */*`). Se confirmó que no es TLS-fingerprinting: `curl` con el mismo UA y headers respondía `200`.
- **Solución**:
  1. `REQUEST_HEADERS` en `pre_scraper.py`: header set de navegador (UA Chrome, `Accept`, `Accept-Language`, `Sec-Fetch-*`, `Upgrade-Insecure-Requests`) enviado en cada request. Con esto el sitio devuelve `200` y la extracción detecta los proyectos reales.
  2. Filtro de enlaces de navegación (`_is_navigational_href`): descarta `href` vacíos, `#...` y `javascript:`. Además `_is_project_url` rechaza URLs que apunten a la raíz o terminen en `#`, para que los 10 resultados sean proyectos concretos y no el menú.
- **Pruebas**: `constructoraberlin.com` → `200`, 10 items (Tempo, Cerezos, Samán, Almendros, Sendero VIS, Peñalar…); regresión `example.com` (200, 2 items), `news.ycombinator.com` (200, 10 items), URL inválida (`422`), red inalcanzable (`502`).
- **Alternativa**: usar un headless browser. Se descarta: el pre-scrape debe seguir siendo shallow/síncrono sin renderizar JS.

### D10: Filtrado estricto de proyectos en el pre-scraper
Refinamiento del filtrado que se aplica dentro de cada etapa de la cascada (metadatos → tarjetas → enlaces) para no llenar el límite de 10 con ruido de navegación/SEO:
1. **Exclusión de contenedores de navegación**: se podan los subárboles `nav`, `header`, `footer`, `aside`/sidebar y menús antes de recolectar candidatos, eliminando ruido estructural del DOM.
2. **Palabras clave negativas**: lista `NEGATIVE_KEYWORDS` (nosotros, aliados, contacto, blog, equipo, faq, login, registro, privacidad, términos…) comparada case-insensitive contra el texto visible y los segmentos de la URL, descartando candidatos no relacionados con proyectos.
3. **Páginas agrupadoras vs. proyectos reales**: heurística que detecta patrones de agrupación/índice/regional (categorías, `/proyectos/`, `/ciudad/…`, paginación `?page=`/`/pagina/`) y prioriza URLs de proyectos concretos; los agrupadores solo se devuelven como último recurso.
- **Respaldo de menú**: la poda estricta es la fuente principal. Si tras ella no se alcanza el límite, se re-examina el HTML original y se toman enlaces tipo-proyecto alojados dentro de los contenedores de navegación (mismo host, sin keywords negativas y sin patrones agrupadores) para llenar el cupo. Esto resuelve el caso de `constructoraberlin.com`, cuyos proyectos viven dentro del `<nav>` de Divi.
- **Alternativa**: no filtrar y devolver enlaces crudos. Se descarta: degrada la precisión del modal de selección con ruido de navegación/SEO.

## Risks / Trade-offs

- [URLs no alcanzables o bloqueadas por robots/rate limits] → Timeouts cortos en `httpx`, captura de excepciones en el servicio y respuesta de error controlada (`502`/`422`), jamás un stacktrace expuesto.
- [Sitios con WAF/CDN estricto devuelven `403` y rompen el pre-scrape] → Cabeceras de navegador (`REQUEST_HEADERS`) como default; si un sitio exige cookie/JS, se documenta y se reevalúa con renderizado headless en una fase posterior. Se mantiene el `502` como respuesta de fallo de fetch.
- [Falsos positivos en la detección de proyectos] → Se podan contenedores de navegación (`nav`/`header`/`footer`/`aside`), se descartan palabras clave negativas (URL y texto) y se priorizan proyectos concretos sobre páginas agrupadoras/regionales. La calidad se refina en deep-scraping.
- [HTML pesado ralentiza el pre-scrape "ultrarrápido"] → Se limita el fetch a un timeout y tamaño máximo de respuesta; el shallow scraping no renderiza JS.
- [bs4/httpx en Python 3.14t (sin GIL)] → Ambos son compatibles con free-threading en sus versiones actuales; si aparece un señalado problema, se documenta y ajusta en el lockfile.
- [Cambio de `main.py` → `app/main.py` puede romper el contenedor existente] → Se actualiza el CMD del Dockerfile en el mismo commit; docker-compose no se toca.

## Migration Plan

1. Añadir dependencias al backend y regenerar `uv.lock`.
2. Crear `Backend/app/` reubicando la app y registrando el router del módulo scraping.
3. Actualizar el `CMD` del `Dockerfile` del backend a `app.main:app`.
4. Crear la feature `scraping` del frontend e integrarla en `App.tsx`.
5. Verificar en local (uvicorn + vite dev) y luego `docker compose up --build`.
6. **Rollback**: revertir el commit; el cambio es aditivo y no altera rutas existentes del frontend salvo `App.tsx`.

## Open Questions

- ¿Se requiere autenticación en el endpoint en fases posteriores?
- ¿El deep-scraping finalmente renderizará JS (headless)? De ser así, definirá nuevas dependencias y flujo asíncrono en un cambio futuro.
- ¿Los proyectos detectados deberán persistirse con un estado (seleccionado/descartado) entre sesiones? Según la respuesta, se define un modelo de datos posterior.