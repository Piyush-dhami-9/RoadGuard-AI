export type Damage = {
  id: number
  class_name: string
  confidence: number
  area: number
  length: number
  width: number
  severity: string
  severity_score: number
  bbox: Record<string, number>
}

export type Inspection = {
  id: number
  timestamp: string
  damage_count: number
  overall_severity: string
  priority_score: number
  inference_mode: string
  model_name: string | null
  model_version: string | null
  image_url: string
  annotated_image_url: string | null
  damages: Damage[]
}

export type Health = {
  status: string
  database: string
  inference_mode: string
  model: { mode: string; model_name: string | null; model_version: string | null; detail: string }
  max_upload_mb: number
}

export const API_BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

const UNREACHABLE = 'The RoadGuard API could not be reached. Check that the backend is running.'

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) return body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join('; ')
  } catch {
    // Not JSON: a proxy or gateway answered instead of the API.
  }
  if (response.status === 413) return 'The image is too large to upload.'
  if (response.status >= 502 && response.status <= 504) return UNREACHABLE
  return `The request failed (HTTP ${response.status}).`
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, init)
  } catch {
    throw new ApiError(0, UNREACHABLE)
  }
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  return response
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError(response.status, 'The server sent an unexpected response. Check the API address configuration.')
  }
}

export const describeError = (error: unknown): string => (error instanceof Error ? error.message : 'Something went wrong.')

/** Health is informative even when degraded (HTTP 503 carries the same body). */
export async function getHealth(): Promise<Health> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/health`)
  } catch {
    throw new ApiError(0, UNREACHABLE)
  }
  try {
    const body = await response.json()
    if (body && typeof body.inference_mode === 'string') return body as Health
  } catch {
    // fall through
  }
  throw new ApiError(response.status, UNREACHABLE)
}

export const listInspections = () => json<Inspection[]>('/inspections')
export const getInspection = (id: number) => json<Inspection>(`/inspection/${id}`)
export const deleteInspection = (id: number) => json<{ deleted: number }>(`/inspection/${id}`, { method: 'DELETE' })

export function detect(file: File): Promise<Inspection> {
  const form = new FormData()
  form.append('file', file)
  return json<Inspection>('/detect', { method: 'POST', body: form })
}

export const assetUrl = (path: string | null): string => (path ? `${API_BASE}${path}` : '')

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export async function downloadReport(id: number): Promise<void> {
  const response = await request(`/report/${id}`)
  saveBlob(await response.blob(), `roadguard-inspection-${id}.pdf`)
}
