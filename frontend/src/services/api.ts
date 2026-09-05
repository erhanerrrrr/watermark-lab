import type {
  ApiCatalog,
  ApiExperimentDetail,
  ApiExperimentSummary,
  ApiHealth,
  DatasetVerification,
  RunExperimentPayload,
  ResearchEvidence,
  GeometryEvidence,
} from '../types'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')

export class ApiUnavailableError extends Error {
  constructor(message = '无法连接本地 FastAPI。请先启动 Watermark Lab 后端。') {
    super(message)
    this.name = 'ApiUnavailableError'
  }
}

export class ApiResponseError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ApiResponseError'
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 10_000): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { cache: 'no-store', ...init, signal: controller.signal })
  } catch (error) {
    const message = error instanceof DOMException && error.name === 'AbortError'
      ? 'API 请求超时，请检查模型是否仍在运行。'
      : undefined
    throw new ApiUnavailableError(message)
  } finally {
    window.clearTimeout(timeout)
  }
  if (!response.ok) {
    let detail = `API 请求失败 (${response.status})`
    try {
      const body = await response.json() as { detail?: string }
      detail = body.detail ?? detail
    } catch { /* response is not JSON */ }
    throw new ApiResponseError(response.status, detail)
  }
  return response.json() as Promise<T>
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

export function getHealth(): Promise<ApiHealth> {
  return request('/health')
}

export function getCatalog(): Promise<ApiCatalog> {
  return request('/catalog')
}

export function listExperiments(limit = 100, model?: string): Promise<ApiExperimentSummary[]> {
  const parameters = new URLSearchParams({ limit: String(limit) })
  if (model) parameters.set('model', model)
  return request(`/experiments?${parameters}`)
}

export function getExperiment(experimentId: string): Promise<ApiExperimentDetail> {
  return request(`/experiments/${encodeURIComponent(experimentId)}`)
}

export function runExperiment(payload: RunExperimentPayload): Promise<ApiExperimentDetail> {
  const form = new FormData()
  form.append('image', payload.image)
  form.append('model', payload.model)
  form.append('message', payload.message)
  form.append('strength', String(payload.strength))
  form.append('attack', payload.attack)
  form.append('attack_parameter', String(payload.attackParameter))
  form.append('device', payload.device ?? 'auto')
  return request('/experiments/single', { method: 'POST', body: form }, 10 * 60_000)
}

export function verifyDatasets(): Promise<DatasetVerification[]> {
  return request('/datasets/verify', { method: 'POST' }, 10 * 60_000)
}

export function manifestUrl(datasetId: string, split: 'debug' | 'calibration' | 'test'): string {
  return apiUrl(`/datasets/${encodeURIComponent(datasetId)}/manifest/${split}`)
}

export function experimentExportUrl(): string {
  return apiUrl('/experiments/export.csv')
}

export function getResearchEvidence(): Promise<ResearchEvidence> {
  return request('/research/evidence', undefined, 30_000)
}

export function researchEvidenceExportUrl(): string {
  return apiUrl('/research/evidence/export.json')
}

export function getGeometryEvidence(): Promise<GeometryEvidence> {
  return request('/research/geometry-v3', undefined, 30_000)
}

export function geometryEvidenceExportUrl(): string {
  return apiUrl('/research/geometry-v3/export.json')
}
