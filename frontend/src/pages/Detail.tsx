import { useEffect, useState } from 'react'
import { AlertTriangle, Download, FileImage, Trash2, TriangleAlert } from 'lucide-react'
import { type Inspection, assetUrl, deleteInspection, describeError, downloadReport, getInspection } from '../api'
import { ModeBadge } from '../components/ModeBadge'
import { SEVERITY_ACTIONS, formatId, modeInfo } from '../lib/inspections'

type Props = { inspectionId: number | null; initial: Inspection | null; goBack: () => void; onDeleted: (id: number) => void }

export function Detail({ inspectionId, initial, goBack, onDeleted }: Props) {
  const [record, setRecord] = useState<Inspection | null>(initial)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState<'' | 'report' | 'delete'>('')
  const [imageFailed, setImageFailed] = useState(false)

  useEffect(() => {
    if (inspectionId === null) return
    let cancelled = false
    setLoadError('')
    getInspection(inspectionId)
      .then((fresh) => { if (!cancelled) setRecord(fresh) })
      .catch((error) => { if (!cancelled) setLoadError(describeError(error)) })
    return () => { cancelled = true }
  }, [inspectionId])

  if (inspectionId === null || (!record && loadError)) {
    return (
      <div className="empty-detail">
        <FileImage size={32} />
        <h2>{loadError || 'Select an inspection'}</h2>
        <button className="primary-btn" onClick={goBack}>Back to history</button>
      </div>
    )
  }
  if (!record) return <div className="loading">Loading inspection...</div>

  const info = modeInfo(record.inference_mode, record.model_name)
  const image = assetUrl(record.annotated_image_url)
  const averageConfidence = record.damages.length ? Math.round((record.damages.reduce((sum, damage) => sum + damage.confidence, 0) / record.damages.length) * 100) : null

  const report = async () => {
    setBusy('report')
    setActionError('')
    try {
      await downloadReport(record.id)
    } catch (error) {
      setActionError(`The report could not be downloaded. ${describeError(error)}`)
    } finally {
      setBusy('')
    }
  }

  const remove = async () => {
    if (!window.confirm(`Delete inspection ${formatId(record.id)} and its images? This cannot be undone.`)) return
    setBusy('delete')
    setActionError('')
    try {
      await deleteInspection(record.id)
      onDeleted(record.id)
    } catch (error) {
      setActionError(`The inspection could not be deleted. ${describeError(error)}`)
      setBusy('')
    }
  }

  return (
    <>
      <section className="page-intro">
        <div>
          <button className="back-btn" onClick={goBack}>← Back to history</button>
          <div className="eyebrow">INSPECTION {formatId(record.id)}</div>
          <h1>Inspection details<span>.</span></h1>
          <p>{new Date(record.timestamp).toLocaleString()} · <ModeBadge mode={record.inference_mode} modelName={record.model_name} /></p>
        </div>
        <div className="intro-actions">
          <button className="secondary-btn" onClick={report} disabled={busy !== ''}>
            <Download size={16} /> {busy === 'report' ? 'Preparing report...' : 'Download report'}
          </button>
          <button className="secondary-btn danger" onClick={remove} disabled={busy !== ''}>
            <Trash2 size={16} /> {busy === 'delete' ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </section>
      {actionError && <div className="notice" role="alert"><TriangleAlert size={17} />{actionError}</div>}
      {info.tone !== 'trained' && <div className={`banner ${info.tone}`} role="note"><AlertTriangle size={17} /><span><b>{info.label}.</b> {info.description}</span></div>}
      <section className="detail-grid">
        <div className="panel image-panel">
          <div className="panel-heading">
            <div><span className="eyebrow">ANNOTATED OUTPUT</span><h2>Flagged regions</h2></div>
          </div>
          {image && !imageFailed ? (
            <img className="annotated" src={image} alt={`Annotated road image for ${formatId(record.id)}`} onError={() => setImageFailed(true)} />
          ) : (
            <div className="image-placeholder"><FileImage size={30} /><span>The annotated image is not available</span></div>
          )}
        </div>
        <div className="panel summary-panel">
          <span className="eyebrow">ESTIMATED RISK</span>
          <div className="score"><strong>{Math.round(record.priority_score)}</strong><span>/ 100<br />repair priority</span></div>
          <div className={`severity-callout ${record.overall_severity.toLowerCase()}`}>
            <AlertTriangle size={18} />
            <div><b>{record.overall_severity} estimated severity</b><span>{SEVERITY_ACTIONS[record.overall_severity] ?? 'Review'}</span></div>
          </div>
          <div className="summary-stat"><span>Detected regions</span><b>{record.damage_count}</b></div>
          <div className="summary-stat"><span>Average confidence</span><b>{averageConfidence === null ? '—' : `${averageConfidence}%`}</b></div>
          <div className="summary-stat"><span>Detector</span><b>{record.model_name ?? 'Not recorded'}</b></div>
          <div className="summary-stat"><span>Detector version</span><b>{record.model_version ?? 'Not recorded'}</b></div>
          <p className="disclaimer">Severity and priority are estimates from image-space (pixel) measurements, not physical dimensions or a certified engineering assessment.</p>
        </div>
      </section>
      <section className="panel damage-list">
        <div className="panel-heading">
          <div><span className="eyebrow">DETECTION BREAKDOWN</span><h2>Detected damage</h2></div>
        </div>
        {record.damages.length === 0 ? <div className="empty">No damage regions were detected in this image.</div> : (
          <div className="damage-cards">
            {record.damages.map((damage) => (
              <div className="damage-card" key={damage.id}>
                <div className="damage-top">
                  <div className="damage-symbol"><TriangleAlert size={17} /></div>
                  <div><b>{damage.class_name}</b><span>{Math.round(damage.confidence * 100)}% confidence</span></div>
                  <span className={`pill ${damage.severity.toLowerCase()}`}><i /> {damage.severity}</span>
                </div>
                <div className="measurements">
                  <div><span>Region area</span><b>{Math.round(damage.area).toLocaleString()} px²</b></div>
                  <div><span>Box long side</span><b>{Math.round(damage.length)} px</b></div>
                  <div><span>Box short side</span><b>{Math.round(damage.width)} px</b></div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
