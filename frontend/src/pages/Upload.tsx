import { type ChangeEvent, type DragEvent, useEffect, useRef, useState } from 'react'
import { Activity, Camera, CircleGauge, CloudUpload, FileImage, FileText, ShieldCheck, X } from 'lucide-react'
import { type Health, type Inspection, describeError, detect } from '../api'
import { ACCEPTED_IMAGE_TYPES, validateImageFile } from '../lib/inspections'

type Props = { health: Health | null; onComplete: (record: Inspection) => void }

export function Upload({ health, onComplete }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const maxUploadMb = health?.max_upload_mb ?? 10
  const mode = health?.inference_mode
  const modelUnavailable = mode === 'unavailable'

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  const clear = () => {
    setFile(null)
    setPreview('')
    if (input.current) input.current.value = ''
  }

  const choose = (selected: File) => {
    const problem = validateImageFile(selected, maxUploadMb)
    if (problem) {
      clear()
      setMessage(problem)
      return
    }
    setFile(selected)
    setPreview(URL.createObjectURL(selected))
    setMessage('')
  }

  const drop = (event: DragEvent) => {
    event.preventDefault()
    const dropped = event.dataTransfer.files[0]
    if (dropped) choose(dropped)
  }

  const analyze = async () => {
    if (!file) return
    setBusy(true)
    setMessage('')
    try {
      onComplete(await detect(file))
    } catch (error) {
      setMessage(describeError(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <section className="page-intro">
        <div>
          <div className="eyebrow">NEW INSPECTION</div>
          <h1>Inspect a road<span>.</span></h1>
          <p>Upload a clear road-surface image to flag damage regions and estimate repair priority.</p>
        </div>
      </section>
      <section className="upload-layout">
        <div className="panel upload-panel">
          <div className="panel-heading">
            <div><span className="eyebrow">STEP 01</span><h2>Choose an image</h2></div>
            <span className="format-note">JPEG, PNG or WebP up to {maxUploadMb} MB</span>
          </div>
          <div
            className={preview ? 'dropzone has-preview' : 'dropzone'}
            role="button"
            tabIndex={0}
            aria-label="Choose a road image"
            onDragOver={(event) => event.preventDefault()}
            onDrop={drop}
            onClick={() => input.current?.click()}
            onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.current?.click() } }}
          >
            {preview ? <img src={preview} alt="Selected road" /> : (
              <>
                <div className="upload-icon"><CloudUpload size={25} /></div>
                <strong>Drop a road image here</strong>
                <span>or browse from your device</span>
              </>
            )}
            <input
              ref={input}
              type="file"
              accept={ACCEPTED_IMAGE_TYPES.join(',')}
              hidden
              data-testid="file-input"
              onChange={(event: ChangeEvent<HTMLInputElement>) => { const selected = event.target.files?.[0]; if (selected) choose(selected) }}
            />
          </div>
          {file && (
            <div className="file-row">
              <FileImage size={17} />
              <div><b>{file.name}</b><span>{(file.size / 1024 / 1024).toFixed(2)} MB ready for inspection</span></div>
              <button onClick={clear} aria-label="Remove selected image"><X size={16} /></button>
            </div>
          )}
          {message && <div className="form-error" role="alert">{message}</div>}
          {modelUnavailable && (
            <div className="form-error" role="alert">
              Inspection is disabled: the trained model is unavailable. {health?.model.detail}
            </div>
          )}
          <button className="primary-btn analyze-btn" disabled={!file || busy || modelUnavailable} onClick={analyze}>
            {busy ? <><Activity size={17} className="spin" /> Inspecting image...</> : <><Camera size={17} /> {mode === 'demo' ? 'Run demo inspection' : 'Run inspection'}</>}
          </button>
          {mode === 'demo' && <p className="disclaimer">Demo mode: the result will come from a placeholder detector, not a trained model.</p>}
        </div>
        <div className="analysis-info">
          <div className="info-card">
            <div className="mini-icon blue"><ShieldCheck size={18} /></div>
            <div><b>Annotated overlay</b><p>See which regions of the image were flagged, and by which detector.</p></div>
          </div>
          <div className="info-card">
            <div className="mini-icon orange"><CircleGauge size={18} /></div>
            <div><b>Estimated severity</b><p>An indicator from image-space measurements. It is not a physical measurement or an engineering assessment.</p></div>
          </div>
          <div className="info-card">
            <div className="mini-icon green"><FileText size={18} /></div>
            <div><b>Report ready</b><p>Download a PDF that states how the result was produced.</p></div>
          </div>
        </div>
      </section>
    </>
  )
}
