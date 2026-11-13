import { vi } from 'vitest'
import type { Health, Inspection } from '../api'

export const demoHealth: Health = {
  status: 'ok',
  database: 'ok',
  inference_mode: 'demo',
  model: { mode: 'demo', model_name: 'opencv-threshold-demo', model_version: '1', detail: 'No trained weights found. Results come from a placeholder, not a trained model.' },
  max_upload_mb: 10,
}

export function inspection(id: number, overrides: Partial<Inspection> = {}): Inspection {
  return {
    id,
    timestamp: `2026-11-${String(id).padStart(2, '0')}T10:00:00Z`,
    damage_count: 1,
    overall_severity: 'Medium',
    priority_score: 50,
    inference_mode: 'demo',
    model_name: 'opencv-threshold-demo',
    model_version: '1',
    image_url: `/inspection/${id}/image/original`,
    annotated_image_url: `/inspection/${id}/image/annotated`,
    damages: [{ id: id * 10, class_name: 'Pothole', confidence: 0.67, area: 45000, length: 321, width: 181, severity: 'Medium', severity_score: 68.1, bbox: { x1: 1, y1: 2, x2: 3, y2: 4 } }],
    ...overrides,
  }
}

type Reply = { status?: number; body?: unknown; raw?: { content: string; type: string } } | Error
type Routes = Record<string, Reply | (() => Reply)>

const respond = (reply: Reply): Response => {
  if (reply instanceof Error) throw reply
  if (reply.raw) return new Response(reply.raw.content, { status: reply.status ?? 200, headers: { 'Content-Type': reply.raw.type } })
  return new Response(JSON.stringify(reply.body ?? null), { status: reply.status ?? 200, headers: { 'Content-Type': 'application/json' } })
}

/** Replaces fetch with a table of "METHOD /path" replies and records every call. */
export function fakeBackend(routes: Routes) {
  const calls: { key: string; init?: RequestInit }[] = []
  const table: Routes = { 'GET /api/health': { body: demoHealth }, 'GET /api/inspections': { body: [] }, ...routes }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(input)}`
    calls.push({ key, init })
    const reply = table[key]
    if (!reply) return respond({ status: 404, body: { detail: `No fake route for ${key}` } })
    return respond(typeof reply === 'function' ? reply() : reply)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, called: (key: string) => calls.filter((call) => call.key === key).length, set: (key: string, reply: Reply) => { table[key] = reply } }
}
