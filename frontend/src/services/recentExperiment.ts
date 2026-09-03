import type { ApiExperimentResult } from '../types'

const KEY = 'watermark-lab:last-experiment'

export function storeRecentExperiment(result: ApiExperimentResult): void {
  sessionStorage.setItem(KEY, JSON.stringify(result))
}

export function loadRecentExperiment(): ApiExperimentResult | null {
  const value = sessionStorage.getItem(KEY)
  if (!value) return null
  try {
    return JSON.parse(value) as ApiExperimentResult
  } catch {
    return null
  }
}
