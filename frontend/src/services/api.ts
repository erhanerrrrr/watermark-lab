import type { ApiExperimentResult, ApiModelInfo, RunExperimentPayload } from '../types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api'

export class ApiUnavailableError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new ApiUnavailableError('无法连接本地 FastAPI，已保留 Mock 展示。')
  }
  if (!response.ok) {
    let detail = `API 请求失败 (${response.status})`
    try {
      const body = await response.json() as { detail?: string }
      detail = body.detail ?? detail
    } catch { /* response is not JSON */ }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export async function checkHealth(): Promise<boolean> {
  try {
    await request('/health')
    return true
  } catch {
    return false
  }
}

export async function listModels(): Promise<ApiModelInfo[]> {
  return request('/models')
}

export async function listExperiments(): Promise<ApiExperimentResult[]> {
  return request('/experiments')
}

export async function runExperiment(payload: RunExperimentPayload): Promise<ApiExperimentResult> {
  const form = new FormData()
  form.append('image', payload.image)
  form.append('model', payload.model)
  form.append('message', payload.message)
  form.append('strength', String(payload.strength))
  form.append('attack', payload.attack)
  form.append('attack_parameter', String(payload.attackParameter))
  form.append('device', payload.device ?? 'auto')
  return request('/experiments/single', { method: 'POST', body: form })
}
