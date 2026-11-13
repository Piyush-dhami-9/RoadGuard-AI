import type { Inspection } from '../api'

export const SEVERITIES = ['Low', 'Medium', 'High', 'Critical'] as const
export const SEVERITY_COLORS: Record<string, string> = { Low: '#2dbb8b', Medium: '#f2a24b', High: '#f05b62', Critical: '#9b1c31' }
export const SEVERITY_ACTIONS: Record<string, string> = { Low: 'Monitor', Medium: 'Schedule repair', High: 'Immediate repair', Critical: 'Urgent repair' }
const SEVERITY_RANK: Record<string, number> = { Low: 1, Medium: 2, High: 3, Critical: 4 }

export const SORT_OPTIONS = {
  newest: 'Newest first',
  oldest: 'Oldest first',
  'severity-desc': 'Most severe first',
  'severity-asc': 'Least severe first',
} as const
export type SortKey = keyof typeof SORT_OPTIONS

export const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']

export const formatId = (id: number): string => `RG-${String(id).padStart(4, '0')}`

export type ModeInfo = { label: string; tone: 'demo' | 'trained' | 'unavailable' | 'unknown'; description: string }

export function modeInfo(mode: string, modelName?: string | null): ModeInfo {
  if (mode === 'trained') return { label: 'TRAINED MODEL', tone: 'trained', description: `Produced by the trained model${modelName ? ` ${modelName}` : ''}.` }
  if (mode === 'demo') return { label: 'DEMO', tone: 'demo', description: 'Produced by a brightness-threshold placeholder, not a trained model. Not an AI prediction.' }
  if (mode === 'unavailable') return { label: 'MODEL UNAVAILABLE', tone: 'unavailable', description: 'A trained model is required but could not be loaded.' }
  return { label: 'SOURCE NOT RECORDED', tone: 'unknown', description: 'This inspection predates detector tracking; treat it as unverified.' }
}

export function filterInspections(records: Inspection[], query: string, severity: string): Inspection[] {
  const needle = query.trim().toLowerCase()
  return records.filter((record) => {
    if (severity !== 'All' && record.overall_severity !== severity) return false
    if (!needle) return true
    const haystack = [
      formatId(record.id),
      String(record.id),
      record.overall_severity,
      modeInfo(record.inference_mode).label,
      new Date(record.timestamp).toLocaleDateString(),
      ...record.damages.map((damage) => damage.class_name),
    ]
    return haystack.some((value) => value.toLowerCase().includes(needle))
  })
}

export function sortInspections(records: Inspection[], key: SortKey): Inspection[] {
  const time = (record: Inspection) => new Date(record.timestamp).getTime()
  const rank = (record: Inspection) => SEVERITY_RANK[record.overall_severity] ?? 0
  const newestFirst = (a: Inspection, b: Inspection) => time(b) - time(a) || b.id - a.id
  const bySeverity = (a: Inspection, b: Inspection) => rank(b) - rank(a) || b.priority_score - a.priority_score
  const compare: Record<SortKey, (a: Inspection, b: Inspection) => number> = {
    newest: newestFirst,
    oldest: (a, b) => newestFirst(b, a),
    'severity-desc': (a, b) => bySeverity(a, b) || newestFirst(a, b),
    'severity-asc': (a, b) => bySeverity(b, a) || newestFirst(a, b),
  }
  return [...records].sort(compare[key])
}

function csvCell(value: string | number | null): string {
  let text = value === null ? '' : String(value)
  // Spreadsheet apps execute cells that start with these characters.
  if (/^[=+\-@\t\r]/.test(text) && typeof value !== 'number') text = `'${text}`
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function toCsv(records: Inspection[]): string {
  const header = ['inspection_id', 'timestamp_utc', 'result_source', 'model_name', 'model_version', 'estimated_severity', 'priority_score', 'damage_count', 'damage_classes']
  const rows = records.map((record) => [
    formatId(record.id),
    new Date(record.timestamp).toISOString(),
    record.inference_mode,
    record.model_name,
    record.model_version,
    record.overall_severity,
    record.priority_score,
    record.damage_count,
    record.damages.map((damage) => damage.class_name).join('; '),
  ])
  return [header, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n'
}

/** Returns a message when the file cannot be uploaded, otherwise null. The server re-validates the content. */
export function validateImageFile(file: File, maxUploadMb: number): string | null {
  const typeOk = file.type ? ACCEPTED_IMAGE_TYPES.includes(file.type) : /\.(jpe?g|png|webp)$/i.test(file.name)
  if (!typeOk) return 'Unsupported file type. Choose a JPEG, PNG or WebP image.'
  if (file.size === 0) return 'This file is empty.'
  if (file.size > maxUploadMb * 1024 * 1024) return `This image is ${(file.size / 1024 / 1024).toFixed(1)} MB; the limit is ${maxUploadMb} MB.`
  return null
}
