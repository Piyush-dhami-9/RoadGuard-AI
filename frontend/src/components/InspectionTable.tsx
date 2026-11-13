import { ArrowUpRight, FileImage } from 'lucide-react'
import type { Inspection } from '../api'
import { formatId } from '../lib/inspections'
import { ModeBadge } from './ModeBadge'

type Props = { records: Inspection[]; openRecord: (record: Inspection) => void; emptyMessage?: string }

function damageSummary(record: Inspection): string {
  const classes = [...new Set(record.damages.map((damage) => damage.class_name))]
  return classes.length ? classes.join(', ') : 'No damage regions'
}

export function InspectionTable({ records, openRecord, emptyMessage = 'No inspections yet. Upload a road image to begin.' }: Props) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Inspection</th>
            <th>Date</th>
            <th>Result source</th>
            <th>Damage found</th>
            <th>Est. severity</th>
            <th>Priority</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {records.length === 0 ? (
            <tr>
              <td colSpan={7} className="empty">{emptyMessage}</td>
            </tr>
          ) : (
            records.map((record) => (
              <tr key={record.id}>
                <td>
                  <div className="inspection-id">
                    <div className="thumb"><FileImage size={15} /></div>
                    <div>
                      <b>{formatId(record.id)}</b>
                      <span>{damageSummary(record)}</span>
                    </div>
                  </div>
                </td>
                <td>{new Date(record.timestamp).toLocaleDateString()}</td>
                <td><ModeBadge mode={record.inference_mode} modelName={record.model_name} /></td>
                <td>{record.damage_count} {record.damage_count === 1 ? 'issue' : 'issues'}</td>
                <td>
                  <span className={`pill ${record.overall_severity.toLowerCase()}`}><i /> {record.overall_severity}</span>
                </td>
                <td>
                  <div className="priority">
                    <b>{Math.round(record.priority_score)}</b>
                    <div><span style={{ width: `${Math.min(100, Math.max(0, record.priority_score))}%` }} /></div>
                  </div>
                </td>
                <td>
                  <button className="row-btn" onClick={() => openRecord(record)} aria-label={`View ${formatId(record.id)}`}>
                    View <ArrowUpRight size={14} />
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
