import { modeInfo } from '../lib/inspections'

export function ModeBadge({ mode, modelName }: { mode: string; modelName?: string | null }) {
  const info = modeInfo(mode, modelName)
  return (
    <span className={`mode-badge ${info.tone}`} title={info.description}>
      {info.label}
    </span>
  )
}
