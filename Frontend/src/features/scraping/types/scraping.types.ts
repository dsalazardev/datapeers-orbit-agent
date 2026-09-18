export const MAX_SELECTED_ITEMS = 10
export const DEFAULT_MAX_ITEMS = 10

export type ProjectSource = 'meta' | 'card' | 'link'

export interface PreScrapeRequest {
  url: string
  max_items?: number
}

export interface ProjectItem {
  id: number
  title: string
  url: string
  source: ProjectSource
}

export interface PreScrapeResponse {
  url: string
  items: ProjectItem[]
  truncated: boolean
}

export type ScrapeReasonCode =
  | 'ORB-SCRAPE-000'
  | 'ORB-SCRAPE-001'
  | 'ORB-SCRAPE-002'
  | 'ORB-SCRAPE-003'
  | 'ORB-SCRAPE-004'
  | 'ORB-SCRAPE-005'

export interface ScrapeErrorDetail {
  reason_code: ScrapeReasonCode | string
  message: string
  request_id: string
  http_status: number
}

export interface ScrapeErrorResponse {
  error: ScrapeErrorDetail
}