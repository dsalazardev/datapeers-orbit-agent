import type {
  PreScrapeRequest,
  PreScrapeResponse,
  ScrapeErrorResponse,
} from '../types/scraping.types'

const PRE_SCRAPE_ENDPOINT = '/api/v1/scraping/pre-scrape'

const REASON_CODE_MESSAGES: Record<string, string> = {
  'ORB-SCRAPE-000': 'Ocurrió un error inesperado al procesar el sitio.',
  'ORB-SCRAPE-001': 'No se pudo cargar el sitio de origen. Revisa la URL e inténtalo de nuevo.',
  'ORB-SCRAPE-002': 'No se pudo interpretar el contenido del sitio.',
  'ORB-SCRAPE-003': 'El sitio no contiene proyectos válidos para esta URL.',
  'ORB-SCRAPE-004': 'El sitio de origen bloqueó la solicitud.',
  'ORB-SCRAPE-005': 'La caché del pre-scrape no está disponible.',
}

async function resolveErrorMessage(response: Response): Promise<string> {
  const fallback = `El pre-scrape falló (HTTP ${response.status})`
  try {
    const body = (await response.json()) as Partial<ScrapeErrorResponse>
    const error = body.error
    if (!error) {
      return fallback
    }
    return REASON_CODE_MESSAGES[error.reason_code] ?? error.message ?? fallback
  } catch {
    return fallback
  }
}

export async function preScrape(request: PreScrapeRequest): Promise<PreScrapeResponse> {
  const response = await fetch(PRE_SCRAPE_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  if (!response.ok) {
    throw new Error(await resolveErrorMessage(response))
  }

  return response.json() as Promise<PreScrapeResponse>
}