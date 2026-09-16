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