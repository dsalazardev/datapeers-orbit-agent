import type { PreScrapeRequest, PreScrapeResponse } from '../types/scraping.types'

const PRE_SCRAPE_ENDPOINT = '/api/v1/scraping/pre-scrape'

export async function preScrape(request: PreScrapeRequest): Promise<PreScrapeResponse> {
  const response = await fetch(PRE_SCRAPE_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  if (!response.ok) {
    throw new Error(`El pre-scrape falló (HTTP ${response.status})`)
  }

  return response.json() as Promise<PreScrapeResponse>
}