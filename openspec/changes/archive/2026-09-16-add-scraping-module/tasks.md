## 1. Backend: estructura del paquete app

- [x] 1.1 Crear `Backend/app/__init__.py` y `Backend/app/modules/__init__.py`
- [x] 1.2 Reubicar la app de `Backend/main.py` a `Backend/app/main.py`, creando la instancia `FastAPI` e incluyendo el router de scraping
- [x] 1.3 Eliminar `Backend/main.py` y actualizar el `CMD` del `Backend/Dockerfile` a `app.main:app`

## 2. Backend: dependencias

- [x] 2.1 Añadir `httpx` y `beautifulsoup4` a `Backend/pyproject.toml`
- [x] 2.2 Sincronizar el entorno con uv y regenerar `Backend/uv.lock`

## 3. Backend: módulo de scraping

- [x] 3.1 Crear `Backend/app/modules/scraping/__init__.py`
- [x] 3.2 Crear `Backend/app/modules/scraping/schemas.py` con `PreScrapeRequest` (URL validada, `max_items` 1–10 con default 10), `ProjectItem` (id, title, url absoluta, source) y `PreScrapeResponse`
- [x] 3.3 Crear `Backend/app/modules/scraping/services/__init__.py`
- [x] 3.4 Crear `Backend/app/modules/scraping/services/pre_scraper.py` con servicio `httpx` + BeautifulSoup: fetch con timeout/tamaño limitado, extracción en cascada (metadatos → tarjetas → `<a>`), resolución de URLs relativas y respeto del límite de 10
- [x] 3.5 Crear `Backend/app/modules/scraping/services/sanitizer.py` con stub `sanitize_html` (limpieza básica: script/style/atributos `on*`)
- [x] 3.6 Crear `Backend/app/modules/scraping/router.py` con `POST /api/v1/scraping/pre-scrape` que valide con schemas, delegue en `pre_scraper` y devuelva `PreScrapeResponse`, con manejo de errores (`422`/`502`)

## 4. Frontend: feature de scraping

- [x] 4.1 Crear `Frontend/src/features/scraping/types/scraping.types.ts` con `PreScrapeRequest`, `ProjectItem`, `PreScrapeResponse` y constantes de límite (10)
- [x] 4.2 Crear `Frontend/src/features/scraping/services/scrapingApi.ts` con la función HTTP que invoca `POST /api/v1/scraping/pre-scrape`
- [x] 4.3 Crear `Frontend/src/features/scraping/hooks/usePreScrape.ts` con estados `loading`, `error` y `data`, y función `run` (reintentable)
- [x] 4.4 Crear `Frontend/src/features/scraping/components/UrlInputForm.tsx` con validación básica de URL y disparo del pre-scrape
- [x] 4.5 Crear `Frontend/src/features/scraping/components/PreScrapeModal.tsx` con listado de proyectos detectados, selección (toggle), límite de 10 y confirmación
- [x] 4.6 Integrar el flujo en `Frontend/src/App.tsx`: formulario → modal → selección confirmada

## 5. Verificación

- [x] 5.1 Verificar lint del frontend (`pnpm lint`) y build de TS (`pnpm build`)
- [x] 5.2 Verificar import/módulos del backend (arranque de uvicorn sin errores)
- [x] 5.3 Probar `POST /api/v1/scraping/pre-scrape` con una URL de ejemplo
- [x] 5.4 Validar `docker compose up --build` con backend y frontend conectados vía proxy `/api/`

## 6. Backend: refinamiento del filtrado de proyectos (pre-scraper)

- [x] 6.1 Reescritura de la extracción en `pre_scraper.py`: podar subárboles de `<nav>`, `<header>`, `<footer>`, `<aside>`/sidebars y menús antes de recolectar candidatos
- [x] 6.2 Implementar listado `NEGATIVE_KEYWORDS` (nosotros, aliados, contacto, blog, equipo, faq, login, registro, privacidad, términos…) con comparación case-insensitive por segmento de palabra y de ruta de URL
- [x] 6.3 Implementar heurística de páginas agrupadoras/regionales (categorías, índices, `/ciudad/…`, paginación `?page=`/`/pagina/`) que descarte o deprioritice candidatos agrupadores frente a proyectos concretos
- [x] 6.4 Integrar las tres capas de filtrado en la cascada (metadatos → tarjetas → enlaces) sin superar el límite de 10 y preservando la resolución de URLs absolutas
- [x] 6.5 Verificación y regresión de `POST /api/v1/scraping/pre-scrape`: contenedores de navegación excluidos, palabras clave negativas descartadas, agrupadoras deprioritizadas; caso base `constructoraberlin.com` con 10 proyectos reales sin menú