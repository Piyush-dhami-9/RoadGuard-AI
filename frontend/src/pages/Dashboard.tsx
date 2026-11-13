import type { ReactNode } from 'react'
import { Activity, AlertTriangle, ArrowUpRight, BarChart3, CircleGauge, FileImage, UploadCloud } from 'lucide-react'
import type { Inspection } from '../api'
import { InspectionTable } from '../components/InspectionTable'
import { SEVERITIES, SEVERITY_COLORS } from '../lib/inspections'

const KNOWN_CLASSES = ['Pothole', 'Longitudinal Crack', 'Transverse Crack', 'Alligator Crack']

type Props = { records: Inspection[]; openRecord: (record: Inspection) => void; goUpload: () => void; goHistory: () => void }

function Kpi({ icon, label, value, note, tone = 'blue' }: { icon: ReactNode; label: string; value: string; note: string; tone?: string }) {
  return (
    <div className="kpi">
      <div className={`kpi-icon ${tone}`}>{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{note}</small>
      </div>
    </div>
  )
}

/** Conic-gradient stops built from the real severity counts. */
function donutBackground(counts: { severity: string; count: number }[], total: number): string {
  if (total === 0) return 'var(--line)'
  let start = 0
  const stops = counts.filter((item) => item.count > 0).map((item) => {
    const end = start + (item.count / total) * 100
    const stop = `${SEVERITY_COLORS[item.severity]} ${start}% ${end}%`
    start = end
    return stop
  })
  return `conic-gradient(${stops.join(', ')})`
}

export function Dashboard({ records, openRecord, goUpload, goHistory }: Props) {
  const severe = records.filter((record) => record.overall_severity === 'High' || record.overall_severity === 'Critical').length
  const averagePriority = records.length ? Math.round(records.reduce((sum, record) => sum + record.priority_score, 0) / records.length) : 0
  const damages = records.flatMap((record) => record.damages)
  const classNames = [...new Set([...KNOWN_CLASSES, ...damages.map((damage) => damage.class_name)])]
  const distribution = classNames.map((name) => ({ name, count: damages.filter((damage) => damage.class_name === name).length }))
  const largest = Math.max(1, ...distribution.map((item) => item.count))
  const severityCounts = SEVERITIES.map((severity) => ({ severity, count: records.filter((record) => record.overall_severity === severity).length }))
    .filter((item) => item.severity !== 'Critical' || item.count > 0)
    .reverse()
  const demoCount = records.filter((record) => record.inference_mode !== 'trained').length

  return (
    <>
      <section className="page-intro">
        <div>
          <div className="eyebrow">FIELD OPERATIONS / OVERVIEW</div>
          <h1>Road network overview<span>.</span></h1>
          <p>Totals across every stored inspection.</p>
        </div>
        <button className="primary-btn" onClick={goUpload}><UploadCloud size={17} /> New inspection</button>
      </section>
      {records.length > 0 && demoCount > 0 && (
        <div className="notice">
          <AlertTriangle size={17} />
          {demoCount === records.length ? 'All' : `${demoCount} of ${records.length}`} inspections below were not produced by a trained model. Figures that include them are illustrative only.
        </div>
      )}
      <section className="kpis">
        <Kpi icon={<FileImage />} label="Total inspections" value={records.length.toString()} note="All time" />
        <Kpi icon={<AlertTriangle />} label="High or critical" value={severe.toString()} note="Estimated severity" tone="red" />
        <Kpi icon={<CircleGauge />} label="Average priority" value={`${averagePriority}/100`} note="Across inspections" tone="orange" />
        <Kpi icon={<Activity />} label="Damage regions" value={damages.length.toString()} note="Detected in total" tone="green" />
      </section>
      <div className="grid-two">
        <section className="panel chart-panel">
          <div className="panel-heading">
            <div><span className="eyebrow">DISTRIBUTION</span><h2>Damage frequency</h2></div>
          </div>
          <div className="bars">
            {distribution.map((item, index) => (
              <div className="bar-row" key={item.name}>
                <span>{item.name.replace(' Crack', '')}</span>
                <div className="bar-track">
                  <div className={`bar bar-${index % 4}`} style={{ width: `${(item.count / largest) * 100}%` }} />
                </div>
                <b>{item.count}</b>
              </div>
            ))}
          </div>
        </section>
        <section className="panel severity-panel">
          <div className="panel-heading">
            <div><span className="eyebrow">RISK PROFILE</span><h2>Severity split</h2></div>
            <BarChart3 size={18} className="muted" />
          </div>
          <div className="donut-wrap">
            <div className="donut" style={{ background: donutBackground(severityCounts, records.length) }}>
              <div><strong>{records.length}</strong><span>cases</span></div>
            </div>
            <div className="legend">
              {severityCounts.map((item) => (
                <div key={item.severity}>
                  <i style={{ background: SEVERITY_COLORS[item.severity] }} />
                  <span>{item.severity}</span>
                  <b>{item.count}</b>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
      <section className="panel recent">
        <div className="panel-heading">
          <div><span className="eyebrow">LATEST</span><h2>Recent inspections</h2></div>
          <button className="text-btn" onClick={goHistory}>View history <ArrowUpRight size={15} /></button>
        </div>
        <InspectionTable records={records.slice(0, 5)} openRecord={openRecord} />
      </section>
    </>
  )
}
