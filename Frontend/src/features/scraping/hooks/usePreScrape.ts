import { useCallback, useState } from 'react'
import type { PreScrapeRequest, PreScrapeResponse } from '../types/scraping.types'
import { preScrape } from '../services/scrapingApi'

interface UsePreScrapeState {
  data: PreScrapeResponse | null
  loading: boolean
  error: string | null
}

const initialState: UsePreScrapeState = {
  data: null,
  loading: false,
  error: null,
}

export function usePreScrape() {
  const [state, setState] = useState<UsePreScrapeState>(initialState)

  const run = useCallback(async (request: PreScrapeRequest) => {
    setState({ data: null, loading: true, error: null })
    try {
      const data = await preScrape(request)
      setState({ data, loading: false, error: null })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error inesperado'
      setState({ data: null, loading: false, error: message })
    }
  }, [])

  const reset = useCallback(() => {
    setState(initialState)
  }, [])

  return { ...state, run, reset }
}