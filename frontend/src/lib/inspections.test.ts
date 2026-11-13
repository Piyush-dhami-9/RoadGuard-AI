import { describe, expect, it } from 'vitest'
import { inspection } from '../test/fakeBackend'
import { filterInspections, formatId, modeInfo, sortInspections, toCsv, validateImageFile } from './inspections'

const records = [
  inspection(1, { overall_severity: 'Low', priority_score: 10 }),
  inspection(2, { overall_severity: 'High', priority_score: 90, damages: [{ ...inspection(2).damages[0], class_name: 'Alligator Crack' }] }),
  inspection(3, { overall_severity: 'Medium', priority_score: 55 }),
  inspection(4, { overall_severity: 'High', priority_score: 75, inference_mode: 'trained', model_name: 'best.pt' }),
]
const ids = (list: { id: number }[]) => list.map((record) => record.id)

describe('filterInspections', () => {
  it('filters by severity', () => expect(ids(filterInspections(records, '', 'High'))).toEqual([2, 4]))
  it('searches by formatted id, damage class and source', () => {
    expect(ids(filterInspections(records, 'rg-0003', 'All'))).toEqual([3])
    expect(ids(filterInspections(records, 'alligator', 'All'))).toEqual([2])
    expect(ids(filterInspections(records, 'trained', 'All'))).toEqual([4])
  })
  it('combines search and severity', () => expect(ids(filterInspections(records, 'pothole', 'High'))).toEqual([4]))
  it('returns everything for a blank query', () => expect(filterInspections(records, '  ', 'All')).toHaveLength(4))
})

describe('sortInspections', () => {
  it('sorts by date both ways without mutating the input', () => {
    expect(ids(sortInspections(records, 'newest'))).toEqual([4, 3, 2, 1])
    expect(ids(sortInspections(records, 'oldest'))).toEqual([1, 2, 3, 4])
    expect(ids(records)).toEqual([1, 2, 3, 4])
  })
  it('sorts by severity, breaking ties by priority', () => {
    expect(ids(sortInspections(records, 'severity-desc'))).toEqual([2, 4, 3, 1])
    expect(ids(sortInspections(records, 'severity-asc'))).toEqual([1, 3, 4, 2])
  })
  it('ranks Critical above High', () => {
    expect(ids(sortInspections([...records, inspection(5, { overall_severity: 'Critical' })], 'severity-desc'))[0]).toBe(5)
  })
})

describe('toCsv', () => {
  it('writes a header and one row per inspection, including the result source', () => {
    const lines = toCsv(records).trim().split('\r\n')
    expect(lines).toHaveLength(5)
    expect(lines[0]).toBe('inspection_id,timestamp_utc,result_source,model_name,model_version,estimated_severity,priority_score,damage_count,damage_classes')
    expect(lines[1]).toBe('RG-0001,2026-11-01T10:00:00.000Z,demo,opencv-threshold-demo,1,Low,10,1,Pothole')
    expect(lines[4]).toContain(',trained,best.pt,')
  })
  it('quotes commas and quotes, and neutralises formula cells', () => {
    const csv = toCsv([inspection(1, { model_name: '=HYPERLINK("x")', damages: [{ ...inspection(1).damages[0], class_name: 'Crack, "wide"' }] })])
    expect(csv).toContain(`"'=HYPERLINK(""x"")"`)
    expect(csv).toContain('"Crack, ""wide"""')
  })
})

describe('validateImageFile', () => {
  const file = (name: string, type: string, size: number) => Object.defineProperty(new File(['x'], name, { type }), 'size', { value: size })
  it('accepts supported images within the limit', () => expect(validateImageFile(file('a.jpg', 'image/jpeg', 5_000_000), 10)).toBeNull())
  it('rejects other types', () => expect(validateImageFile(file('a.pdf', 'application/pdf', 100), 10)).toMatch(/Unsupported/))
  it('rejects empty and oversized files', () => {
    expect(validateImageFile(file('a.png', 'image/png', 0), 10)).toMatch(/empty/)
    expect(validateImageFile(file('a.png', 'image/png', 11 * 1024 * 1024), 10)).toMatch(/limit is 10 MB/)
  })
})

describe('labels', () => {
  it('formats ids', () => expect(formatId(7)).toBe('RG-0007'))
  it('never labels demo or unknown results as trained', () => {
    expect(modeInfo('demo').label).toBe('DEMO')
    expect(modeInfo('trained', 'best.pt').label).toBe('TRAINED MODEL')
    expect(modeInfo('unknown').tone).toBe('unknown')
    expect(modeInfo('something-new').tone).toBe('unknown')
  })
})
