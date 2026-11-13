import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { demoHealth, fakeBackend, inspection } from './test/fakeBackend'

const imageFile = (name = 'road.jpg', type = 'image/jpeg', bytes = 1024) => new File([new Uint8Array(bytes)], name, { type })
const user = () => userEvent.setup({ applyAccept: false })
const openPage = async (name: string) => userEvent.click(await screen.findByRole('button', { name }))
let savedBlobs: Blob[]

beforeEach(() => {
  savedBlobs = []
  URL.createObjectURL = vi.fn((blob: Blob) => { savedBlobs.push(blob); return 'blob:fake' })
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

describe('model status', () => {
  it('shows DEMO mode from the API and none of the old hardcoded claims', async () => {
    fakeBackend({})
    render(<App />)
    expect(await screen.findByText(/DEMO MODE\./)).toBeInTheDocument()
    expect(screen.getByText('DEMO mode · no trained model')).toBeInTheDocument()
    expect(screen.queryByText(/Model ready/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/AI segmentation/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Jordan/)).not.toBeInTheDocument()
  })

  it('shows the trained model name and no demo banner in trained mode', async () => {
    fakeBackend({ 'GET /api/health': { body: { ...demoHealth, inference_mode: 'trained', model: { mode: 'trained', model_name: 'best.pt', model_version: 'abc123', detail: 'loaded' } } } })
    render(<App />)
    expect(await screen.findByText('Trained model · best.pt')).toBeInTheDocument()
    expect(screen.queryByText(/DEMO MODE\./)).not.toBeInTheDocument()
  })

  it('disables inspection when the trained model is unavailable', async () => {
    fakeBackend({ 'GET /api/health': { body: { ...demoHealth, status: 'degraded', inference_mode: 'unavailable', model: { mode: 'unavailable', model_name: null, model_version: null, detail: 'Weights failed to load.' } } } })
    render(<App />)
    expect(await screen.findByText(/MODEL UNAVAILABLE\./)).toBeInTheDocument()
    await openPage('Upload inspection')
    await user().upload(screen.getByTestId('file-input'), imageFile())
    expect(screen.getByRole('button', { name: /Run inspection/ })).toBeDisabled()
    expect(screen.getByText(/Inspection is disabled/)).toBeInTheDocument()
  })

  it('has no dead Settings, Search or Notifications controls', async () => {
    fakeBackend({})
    render(<App />)
    await screen.findByText('Road network overview')
    for (const name of [/settings/i, /notification/i, /^search$/i, /this year/i]) expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
  })
})

describe('API errors', () => {
  it('explains an unreachable API and recovers on retry', async () => {
    const backend = fakeBackend({ 'GET /api/inspections': new TypeError('Failed to fetch'), 'GET /api/health': new TypeError('Failed to fetch') })
    render(<App />)
    expect(await screen.findByText(/could not be reached/)).toBeInTheDocument()
    expect(screen.getByText('API unreachable')).toBeInTheDocument()
    backend.set('GET /api/inspections', { body: [inspection(1)] })
    backend.set('GET /api/health', { body: demoHealth })
    await userEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(await screen.findByText('RG-0001')).toBeInTheDocument()
    expect(screen.queryByText(/could not be reached/)).not.toBeInTheDocument()
  })

  it('reports a non-JSON answer (misconfigured API address) instead of crashing', async () => {
    fakeBackend({ 'GET /api/inspections': { raw: { content: '<!doctype html>', type: 'text/html' } } })
    render(<App />)
    expect(await screen.findByText(/unexpected response/)).toBeInTheDocument()
  })
})

describe('upload workflow', () => {
  it('uploads an image and shows the labelled result', async () => {
    const backend = fakeBackend({ 'POST /api/detect': { body: inspection(12) }, 'GET /api/inspection/12': { body: inspection(12) } })
    render(<App />)
    await openPage('Upload inspection')
    expect(screen.getByText('JPEG, PNG or WebP up to 10 MB')).toBeInTheDocument()
    const run = screen.getByRole('button', { name: /Run demo inspection/ })
    expect(run).toBeDisabled()
    await user().upload(screen.getByTestId('file-input'), imageFile())
    await userEvent.click(run)

    expect(await screen.findByText('INSPECTION RG-0012')).toBeInTheDocument()
    const sent = backend.calls.find((call) => call.key === 'POST /api/detect')!.init!.body as FormData
    expect((sent.get('file') as File).name).toBe('road.jpg')
    expect(screen.getByRole('img', { name: /Annotated road image/ })).toHaveAttribute('src', '/api/inspection/12/image/annotated')
    expect(screen.getByText('Pothole')).toBeInTheDocument()
    expect(screen.getByText('67% confidence')).toBeInTheDocument()
    expect(screen.getByText('Medium estimated severity')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('DEMO. Produced by a brightness-threshold placeholder')
    expect(screen.getByText(/not physical dimensions or a certified engineering assessment/)).toBeInTheDocument()
  })

  it('shows the server explanation when the upload is rejected', async () => {
    fakeBackend({ 'POST /api/detect': { status: 415, body: { detail: 'Unsupported file type. Upload a JPEG, PNG or WebP image' } } })
    render(<App />)
    await openPage('Upload inspection')
    await user().upload(screen.getByTestId('file-input'), imageFile())
    await userEvent.click(screen.getByRole('button', { name: /Run demo inspection/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Unsupported file type. Upload a JPEG, PNG or WebP image')
    expect(screen.getByText('Inspect a road')).toBeInTheDocument()
  })

  it('reports a model outage returned by the server', async () => {
    fakeBackend({ 'POST /api/detect': { status: 503, body: { detail: 'Inspection is unavailable: weights failed to load' } } })
    render(<App />)
    await openPage('Upload inspection')
    await user().upload(screen.getByTestId('file-input'), imageFile())
    await userEvent.click(screen.getByRole('button', { name: /Run demo inspection/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('weights failed to load')
  })

  it('rejects wrong types and oversized files before calling the API', async () => {
    const backend = fakeBackend({ 'GET /api/health': { body: { ...demoHealth, max_upload_mb: 1 } } })
    render(<App />)
    await openPage('Upload inspection')
    await user().upload(screen.getByTestId('file-input'), imageFile('notes.pdf', 'application/pdf'))
    expect(screen.getByRole('alert')).toHaveTextContent('Unsupported file type')
    await user().upload(screen.getByTestId('file-input'), imageFile('huge.jpg', 'image/jpeg', 2 * 1024 * 1024))
    expect(screen.getByRole('alert')).toHaveTextContent('the limit is 1 MB')
    expect(screen.getByRole('button', { name: /Run demo inspection/ })).toBeDisabled()
    expect(backend.called('POST /api/detect')).toBe(0)
  })
})

describe('inspection history', () => {
  const records = [
    inspection(3, { overall_severity: 'Low', priority_score: 12 }),
    inspection(2, { overall_severity: 'High', priority_score: 88, damages: [{ ...inspection(2).damages[0], class_name: 'Alligator Crack' }] }),
    inspection(1, { overall_severity: 'Medium' }),
  ]
  const rowIds = () => screen.getAllByText(/^RG-\d+$/).map((cell) => cell.textContent)

  it('searches, filters by severity and sorts', async () => {
    fakeBackend({ 'GET /api/inspections': { body: records } })
    render(<App />)
    await openPage('Inspection history')
    expect(rowIds()).toEqual(['RG-0003', 'RG-0002', 'RG-0001'])

    await userEvent.selectOptions(screen.getByLabelText('Sort inspections'), 'severity-desc')
    expect(rowIds()).toEqual(['RG-0002', 'RG-0001', 'RG-0003'])
    await userEvent.selectOptions(screen.getByLabelText('Sort inspections'), 'oldest')
    expect(rowIds()).toEqual(['RG-0001', 'RG-0002', 'RG-0003'])

    await userEvent.selectOptions(screen.getByLabelText('Filter by severity'), 'High')
    expect(rowIds()).toEqual(['RG-0002'])
    expect(screen.getByText('Showing 1 of 3 inspections')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Filter by severity'), 'All')
    await userEvent.type(screen.getByLabelText('Search inspections'), 'alligator')
    expect(rowIds()).toEqual(['RG-0002'])
    await userEvent.clear(screen.getByLabelText('Search inspections'))
    await userEvent.type(screen.getByLabelText('Search inspections'), 'zzz')
    expect(screen.getByText('No inspections match the current search and filter.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Export CSV/ })).toBeDisabled()
  })

  it('exports the visible rows as CSV', async () => {
    fakeBackend({ 'GET /api/inspections': { body: records } })
    render(<App />)
    await openPage('Inspection history')
    await userEvent.selectOptions(screen.getByLabelText('Filter by severity'), 'High')
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV (1)' }))
    expect(savedBlobs).toHaveLength(1)
    const lines = (await savedBlobs[0].text()).trim().split('\r\n')
    expect(lines).toHaveLength(2)
    expect(lines[1]).toContain('RG-0002')
    expect(lines[1]).toContain(',demo,')
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce()
  })

  it('shows an empty state when there are no inspections', async () => {
    fakeBackend({})
    render(<App />)
    await openPage('Inspection history')
    expect(screen.getByText('No inspections yet. Upload a road image to begin.')).toBeInTheDocument()
  })

  it('marks each row with its result source', async () => {
    fakeBackend({ 'GET /api/inspections': { body: [inspection(2, { inference_mode: 'trained', model_name: 'best.pt' }), inspection(1, { inference_mode: 'unknown', model_name: null })] } })
    render(<App />)
    await openPage('Inspection history')
    const rows = screen.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('TRAINED MODEL')).toBeInTheDocument()
    expect(within(rows[1]).getByText('SOURCE NOT RECORDED')).toBeInTheDocument()
  })
})

describe('inspection detail', () => {
  const open = async (backendRoutes = {}) => {
    const backend = fakeBackend({ 'GET /api/inspections': { body: [inspection(5), inspection(4)] }, 'GET /api/inspection/5': { body: inspection(5) }, ...backendRoutes })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'View RG-0005' }))
    await screen.findByText('INSPECTION RG-0005')
    return backend
  }

  it('downloads the PDF report with a GET request', async () => {
    const backend = await open({ 'GET /api/report/5': { raw: { content: '%PDF-1.4', type: 'application/pdf' } } })
    await userEvent.click(screen.getByRole('button', { name: /Download report/ }))
    await waitFor(() => expect(savedBlobs).toHaveLength(1))
    expect(backend.called('GET /api/report/5')).toBe(1)
    expect(await savedBlobs[0].text()).toBe('%PDF-1.4')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('reports a failed report download', async () => {
    await open({ 'GET /api/report/5': { status: 404, body: { detail: 'Inspection not found' } } })
    await userEvent.click(screen.getByRole('button', { name: /Download report/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The report could not be downloaded. Inspection not found')
    expect(savedBlobs).toHaveLength(0)
  })

  it('deletes after confirmation and returns to history', async () => {
    const backend = await open({ 'DELETE /api/inspection/5': { body: { deleted: 5 } } })
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    await userEvent.click(screen.getByRole('button', { name: /Delete/ }))
    expect(backend.called('DELETE /api/inspection/5')).toBe(0)

    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    await userEvent.click(screen.getByRole('button', { name: /Delete/ }))
    expect(await screen.findByLabelText('Search inspections')).toBeInTheDocument()
    expect(backend.called('DELETE /api/inspection/5')).toBe(1)
    expect(screen.queryByText('RG-0005')).not.toBeInTheDocument()
    expect(screen.getByText('RG-0004')).toBeInTheDocument()
  })

  it('falls back to a placeholder when the image cannot be loaded', async () => {
    await open()
    screen.getByRole('img', { name: /Annotated road image/ }).dispatchEvent(new Event('error'))
    expect(await screen.findByText('The annotated image is not available')).toBeInTheDocument()
  })
})

describe('navigation', () => {
  it('opens and closes the mobile navigation', async () => {
    fakeBackend({})
    render(<App />)
    const toggle = await screen.findByRole('button', { name: 'Open navigation' })
    await userEvent.click(toggle)
    expect(document.querySelector('.sidebar')).toHaveClass('open')
    await userEvent.click(screen.getByRole('button', { name: 'Inspection history' }))
    expect(document.querySelector('.sidebar')).not.toHaveClass('open')
  })

  it('links the dashboard to history', async () => {
    fakeBackend({ 'GET /api/inspections': { body: [inspection(1)] } })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /View history/ }))
    expect(screen.getByLabelText('Search inspections')).toBeInTheDocument()
  })
})
