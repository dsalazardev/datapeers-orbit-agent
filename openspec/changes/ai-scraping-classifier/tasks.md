## 1. Configuración LLM

- [x] 1.1 Añadir a `Backend/app/core/settings.py` los campos `openrouter_api_key: str | None = None`, `llm_model: str = "deepseek/deepseek-v4-flash-0731:free"`, `llm_timeout: float = 8.0` y `llm_max_tokens: int = 4096`
- [x] 1.2 Documentar `ORBIT_OPENROUTER_API_KEY`, `ORBIT_LLM_MODEL`, `ORBIT_LLM_TIMEOUT`, `ORBIT_LLM_MAX_TOKENS` en `Backend/.env.example`

## 2. Cliente LLM (`app/modules/scraping/llm.py`)

- [x] 2.1 Definir el esquema Pydantic estricto `ProjectCard` (`is_project: bool`, `is_active_project: bool`, `title: str`, `description_summary: str | None`, `price_from: str | None`, `status_badge: Literal["Preventa","Entrega Inmediata","Agotado","Desconocido"]`, `score: int`)
- [x] 2.2 Implementar el prompt del sistema en español con el contrato JSON y la instrucción de `price_from = null` cuando el HTML no muestra precio (antialucinación)
- [x] 2.3 Implementar `LLMProjectClassifier` como cliente async sobre `httpx.AsyncClient` (POST `{base_url}/chat/completions`, `Authorization: Bearer`, `response_format` json_object si aplica, timeout configurable)
- [x] 2.4 Parseo robusto de la respuesta (strip de fences ```` ```json ````) y validación estricta contra `ProjectCard`; respuesta no válida → señal de fallback sin propagar contenido crudo
- [x] 2.5 Mapear `ProjectCard` → campos aditivos de `ProjectItem` (`is_active_project`, `status_badge`, `price_from`); `description_summary` queda interno (no se expone en el API)

## 3. Catálogo de errores

- [x] 3.1 Añadir `LLM_UNAVAILABLE = "ORB-SCRAPE-006"` (log-only, sin http_status de error) al catálogo de `errors.py`, usado solo en logging de fallback

## 4. Contrato aditivo

- [x] 4.1 Ampliar `ProjectItem` en `schemas.py` con `is_active_project: bool | None = None`, `status_badge: Literal["Preventa","Entrega Inmediata","Agotado","Desconocido"] | None = None`, `price_from: str | None = None`, preservando `title`, `url`, `source`
- [x] 4.2 Añadir `meta: ScrapeMeta | None = None` (con `filtered_out: int`) a `PreScrapeResponse` en `schemas.py`

## 5. Integración y wiring

- [x] 5.1 Inyectar `classifier: LLMProjectClassifier | None = None` en `PreScraperService`; en el flujo `live`, post-normalización y pre-respuesta: clasificar, descartar `is_project == false`, enriquecer ítems y re-aplicar `MAX_ITEMS`
- [x] 5.2 Fallback en `PreScraperService`: sin key / timeout (8s) / error de red / HTTP no-2xx / schema inválido → ítems deterministas con `is_active_project = None`, sin error 500 al usuario, log `source=fallback` con `reason_code=ORB-SCRAPE-006`
- [x] 5.3 Construir e inyectar el clasificador en `create_app()`/`_default_pre_scraper` (solo si hay API key), expuesto en `app.state.pre_scraper`; cache/seed nunca invocan el LLM
- [x] 5.4 Cero ítems post-filtro: si el LLM descarta todos los candidatos, responder `200 OK` con `items: []` y `meta.filtered_out = N` (sin error)

## 6. Golden dataset y tests

- [ ] 6.1 Crear `Backend/tests/fixtures/scraping/golden/` con 10 URLs reales (HTML congelado) y `expected.json` (etiquetas `is_project` y precio esperado)
- [x] 6.2 Test: batch único — el clasificador hace UNA llamada para ≤10 candidatos (assert transporte/llamadas), nunca una por candidato
- [ ] 6.3 Test: schema inválido — respuesta que no valida contra `ProjectCard` → fallback determinista, sin contenido crudo
- [ ] 6.4 Test: timeout — inyectar `LLMProjectClassifier(timeout=0.1)` con un mock que duerme 1s; la llamada agota el timeout y provoca fallback con `source=fallback` y `reason_code=ORB-SCRAPE-006` (evita esperar 8s reales en pytest)
- [ ] 6.5 Test: fallback de red/HTTP — error del proveedor devuelve 200 OK con `is_active_project = None`, nunca 500 ni texto crudo
- [ ] 6.6 Test: sin API key — flujo `live` devuelve ítems deterministas con `is_active_project = None` y el LLM nunca se invoca
- [ ] 6.7 Test: campos aditivos — `ProjectItem` con `is_active_project`/`status_badge`/`price_from` correctos tras clasificar, preservando `title`/`url`/`source`
- [ ] 6.8 Test: cache/seed sin LLM — hit de caché o seed responde < 200ms sin invocar el clasificador (mock no llamado)
- [x] 6.9 Test: mock OpenRouter — toda la suite usa `httpx.MockTransport`/stub; cero llamadas reales y cero consumo de tokens
- [ ] 6.10 Evaluación golden: precisión `is_project` ≥ 90% y cero alucinaciones de `price_from` (con respuestas grabadas o `ORBIT_LLM_EVAL_REAL=1`)
- [ ] 6.11 Test: desalineación del batch — respuesta con longitud distinta a los candidatos o índices rotos (no 1:1) → fallback completo determinista
- [ ] 6.12 Test: cero ítems post-filtro — si el LLM descarta todos los candidatos, respuesta `200 OK` con `items: []` y `meta.filtered_out = N`, sin error

## 7. Verificación

- [ ] 7.1 Ejecutar `openspec validate ai-scraping-classifier` sin errores
- [ ] 7.2 Ejecutar la suite de backend en verde (tests existentes + nuevos)
- [ ] 7.3 Verificar arranque `uvicorn app.main:app` y una llamada manual a `POST /api/v1/scraping/pre-scrape` con y sin API key (fallback visible)

## 8. Coordinación frontend (tipos opcionales)

- [ ] 8.1 Ampliar tipos opcionales en `Frontend/src/features/scraping/types/scraping.types.ts` (`is_active_project`, `status_badge`, `price_from` y `meta`) — aditivo, no breaking
- [ ] 8.2 Verificar el build del frontend sin errores (script `build` de `Frontend/package.json`, p. ej. `pnpm build`)