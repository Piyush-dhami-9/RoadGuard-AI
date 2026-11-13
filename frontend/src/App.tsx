import { type ComponentType, useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CalendarDays, ChevronRight, CloudUpload, LayoutDashboard, Menu, Moon, RefreshCw, ShieldCheck, Sun, TriangleAlert, X } from 'lucide-react'
import { type Health, type Inspection, describeError, getHealth, listInspections } from './api'
import { modeInfo } from './lib/inspections'
import { Dashboard } from './pages/Dashboard'
import { Detail } from './pages/Detail'
import { History } from './pages/History'
import { Upload } from './pages/Upload'

type Page = 'Dashboard' | 'Upload inspection' | 'Inspection history' | 'Inspection detail'
const NAVIGATION: [Page, ComponentType<{ size?: number }>][] = [
  ['Dashboard', LayoutDashboard],
  ['Upload inspection', CloudUpload],
  ['Inspection history', CalendarDays],
]

function SystemStatus({ health, offline }: { health: Health | null; offline: boolean }) {
  if (offline || !health) {
    return <div className="system-status"><span className="status-dot off" />API unreachable<small>Status unknown</small></div>
  }
  const info = modeInfo(health.inference_mode, health.model.model_name)
  const healthy = health.status === 'ok'
  return (
    <div className="system-status" title={health.model.detail}>
      <span className={healthy ? 'status-dot' : 'status-dot warn'} />
      {health.database === 'ok' ? 'API online' : 'Database unavailable'}
      <small>
        {info.tone === 'trained' ? `Trained model · ${health.model.model_name}` : info.tone === 'demo' ? 'DEMO mode · no trained model' : 'Trained model unavailable'}
      </small>
    </div>
  )
}

function App() {
  const [page, setPage] = useState<Page>('Dashboard')
  const [records, setRecords] = useState<Inspection[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [dark, setDark] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [navOpen, setNavOpen] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    const [healthResult, recordsResult] = await Promise.allSettled([getHealth(), listInspections()])
    setHealth(healthResult.status === 'fulfilled' ? healthResult.value : null)
    if (recordsResult.status === 'fulfilled') {
      setRecords(recordsResult.value)
      setError('')
    } else {
      setError(describeError(recordsResult.reason))
    }
    setLoading(false)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const go = (target: Page) => { setPage(target); setNavOpen(false) }
  const openRecord = (record: Inspection) => { setSelectedId(record.id); go('Inspection detail') }
  const selected = records.find((record) => record.id === selectedId) ?? null
  const mode = health?.inference_mode

  return (
    <div className={dark ? 'app dark' : 'app'}>
      <aside className={navOpen ? 'sidebar open' : 'sidebar'} id="primary-navigation">
        <div className="brand">
          <div className="brand-mark"><ShieldCheck size={22} /></div>
          <div><strong>RoadGuard</strong><span>ROAD INSPECTIONS</span></div>
        </div>
        <nav aria-label="Primary">
          {NAVIGATION.map(([label, Icon]) => (
            <button className={page === label ? 'nav-item active' : 'nav-item'} onClick={() => go(label)} key={label} aria-current={page === label ? 'page' : undefined}>
              <Icon size={18} /><span>{label}</span>{page === label && <ChevronRight size={15} />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom"><SystemStatus health={health} offline={Boolean(error)} /></div>
      </aside>
      {navOpen && <div className="nav-backdrop" onClick={() => setNavOpen(false)} />}
      <main>
        <header>
          <button className="mobile-menu" onClick={() => setNavOpen(!navOpen)} aria-label={navOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={navOpen} aria-controls="primary-navigation">
            {navOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <div className="crumb"><span>Workspace</span><ChevronRight size={14} /><b>{page}</b></div>
          <div className="header-actions">
            <button className="theme-btn" onClick={() => setDark(!dark)}>
              {dark ? <Sun size={17} /> : <Moon size={17} />}<span>{dark ? 'Light' : 'Dark'}</span>
            </button>
          </div>
        </header>
        <div className="content">
          {mode === 'demo' && (
            <div className="banner demo" role="status">
              <AlertTriangle size={17} />
              <span><b>DEMO MODE.</b> No trained model is installed. New inspections use a brightness-threshold placeholder and are not AI predictions.</span>
            </div>
          )}
          {mode === 'unavailable' && (
            <div className="banner unavailable" role="alert">
              <AlertTriangle size={17} />
              <span><b>MODEL UNAVAILABLE.</b> New inspections are disabled. {health?.model.detail}</span>
            </div>
          )}
          {error && (
            <div className="notice" role="alert">
              <TriangleAlert size={17} />
              <span>{error}</span>
              <button className="text-btn" onClick={refresh}><RefreshCw size={14} /> Retry</button>
            </div>
          )}
          {loading ? <div className="loading" role="status">Loading inspection workspace...</div>
            : page === 'Dashboard' ? <Dashboard records={records} openRecord={openRecord} goUpload={() => go('Upload inspection')} goHistory={() => go('Inspection history')} />
            : page === 'Upload inspection' ? <Upload health={health} onComplete={(record) => { setRecords((current) => [record, ...current]); openRecord(record) }} />
            : page === 'Inspection history' ? <History records={records} openRecord={openRecord} />
            : <Detail key={selectedId} inspectionId={selectedId} initial={selected} goBack={() => go('Inspection history')} onDeleted={(id) => { setRecords((current) => current.filter((record) => record.id !== id)); setSelectedId(null); go('Inspection history') }} />}
        </div>
      </main>
    </div>
  )
}

export default App
