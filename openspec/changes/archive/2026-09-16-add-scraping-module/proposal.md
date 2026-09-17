## Why

ORBIT necesita una capacidad de scraping web para que el usuario pueda detectar y seleccionar proyectos desde una URL fuente. Hoy el proyecto es solo scaffolding (backend FastAPI minimalista y frontend React template), sin ninguna funcionalidad de extracción de datos.

## What Changes

- **Backend**: se introduce el módulo `scraping` bajo `Backend/app/modules/scraping/` con su endpoint `POST /api/v1/scraping/pre-scrape`, modelos Pydantic (`PreScrapeRequest`, `ProjectItem`, `PreScrapeResponse`) y servicios (`pre_scraper.py`, `sanitizer.py`). La app principal de FastAPI pasa de `Backend/main.py` a `Backend/app/main.py` y registra el router del módulo.
- **Frontend**: se introduce la feature `scraping` bajo `Frontend/src/features/scraping/` con tipos TypeScript, cliente HTTP (`scrapingApi.ts`), componente de formulario de URL (`UrlInputForm`), modal de selección de proyectos (`PreScrapeModal`, límite 10) y hook de estado (`usePreScrape`).
- **Flujo**: el usuario ingresa una URL → pre-scraping shallow (máximo 10 proyectos) → modal de selección → base para deep-scraping posterior.

## Capabilities

### New Capabilities
- `scraping`: detección rápida (shallow scraping) de proyectos/enlaces desde una URL ingresada por el usuario, con devolución inmediata de un listado (máximo 10 ítems) para selección en un modal, y estructura base para el deep-scraping asíncrono posterior.

### Modified Capabilities
<!-- No existing specs. openspec/specs/ está vacío (solo .gitkeep). -->

## Impact

- **Backend** (`Backend/`): nueva estructura `app/`, dependencias nuevas `httpx` y `beautifulsoup4`, reubicación de `main.py`, cambios en `Dockerfile`/`docker-compose` si es necesario (comando de arranque apunta a `app.main:app`).
- **Frontend** (`Frontend/`): nueva estructura `features/scraping/`, componente `App.tsx` que integra el formulario y el modal, consumo de `/api` vía proxy de nginx (ya configurado: `/api/` → `backend:8000`).
- **API**: nuevo endpoint `POST /api/v1/scraping/pre-scrape`.
- **Dependencias**: backend suma `httpx` y `beautifulsoup4`; se actualizan `pyproject.toml`/`uv.lock`.