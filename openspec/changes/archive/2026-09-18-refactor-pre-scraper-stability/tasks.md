## 1. Desacople del pre_scraper en submódulos

- [x] 1.1 Extraer las reglas de filtrado (keywords negativas, índices, regionales, slugs) de `pre_scraper.py` a `Backend/app/modules/scraping/config.py`, eliminando los términos hardcodeados de cliente (JYP) y dejando la lista sin duplicados
- [x] 1.2 Crear los submódulos del scraper: fetch HTTP, parseo de HTML (BeautifulSoup), extracción de candidatos y construcción de ítems, migrando la lógica de `PreScraper` sin cambiar el comportamiento externo
- [x] 1.3 Corregir el desajuste de tipos: `Candidate` debe aceptar `"grouping"` en su `Literal` y todas las funciones/métodos deben quedar anotadas

## 2. Parseo en thread pool (anyio)

- [x] 2.1 Ejecutar el parseo CPU-bound de BeautifulSoup dentro de `anyio.to_thread` en el flujo async de `pre_scraper`, garantizando que el event loop queda libre
- [x] 2.2 Eliminar el re-parseo del HTML (segundo `BeautifulSoup(html)`) haciendo que los extractores compartan un único árbol parseado

## 3. Configuración externa de reglas de cliente

- [x] 3.1 Mover los límites del scraper (timeout, tamaño máximo de cuerpo) y las listas de keywords a `Settings` con variables `ORBIT_*` documentadas en `Backend/.env.example`
- [x] 3.2 Verificar con `grep -ri jyp Backend/app/modules/scraping` que no queden términos de cliente en el código de dominio (0 coincidencias)

## 4. Errores normalizados con reason_codes

- [x] 4.1 Definir el catálogo de `reason_codes` `ORB-SCRAPE-XXX` (p. ej. `ORB-SCRAPE-001` fetch/timeout, `ORB-SCRAPE-002` parseo, `ORB-SCRAPE-003` respuesta inválida) y un esquema de error seguro
- [x] 4.2 Actualizar `scraping/router.py` para devolver errores con `reason_code` estable y sin texto crudo de la excepción (ORB-NFR-005), eliminando `detail=str(exc)`
- [x] 4.3 Asegurar que el 100% de los errores manejados del router incluyen `reason_code`

## 5. Caché local / seeded fallback

- [x] 5.1 Implementar la caché local del scraper (filesystem/JSON) con persistencia de resultados por URL
- [x] 5.2 Implementar el seeded fallback: si la URL falla y no hay caché, responder en < 200ms con datos sembrados para resiliencia en demo
- [x] 5.3 Conectar caché + seeded fallback al flujo del espera/error del `PreScraper` sin alterar el contrato de éxito

## 6. Tests de regresión

- [x] 6.1 Añadir tests para la caché local (hit de caché, persistencia y seeded fallback < 200ms)
- [x] 6.2 Añadir tests para los `reason_codes` del router (sin texto crudo y con 100% de cobertura de errores)
- [x] 6.3 Medir concurrencia: durante 50 requests concurrentes a `/pre-scrape`, un endpoint liviano (`GET /health`) debe responder con P95 < 100ms, confirmando que el event loop no se bloquea
- [x] 6.4 Comprobar `grep "jyp" = 0` en `/domain/` como test de regresión del dominio
- [x] 6.5 Ejecutar la suite completa y verificar que todos los tests quedan en verde

## 7. Verificación

- [x] 7.1 Validar `openspec validate refactor-pre-scraper-stability` sin errores
- [x] 7.2 Verificar build/arranque del backend (`uvicorn app.main:app`) sin errores de import
- [x] 7.3 Confirmar `docker compose up --build` con el pre-scrape funcionando

## 8. Coordinación frontend (mínima)

- [x] 8.1 Añadir mapeo `reason_code → mensaje` en `scrapingApi.ts` para capturar la estructura `{error: {reason_code, message}}`
- [x] 8.2 Verificar que el modal del frontend renderiza el mensaje de error correctamente