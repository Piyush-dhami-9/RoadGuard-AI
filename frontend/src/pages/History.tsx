import { useMemo, useState } from 'react'
import { Download, Search } from 'lucide-react'
import { saveBlob, type Inspection } from '../api'
import { InspectionTable } from '../components/InspectionTable'
import { SEVERITIES, SORT_OPTIONS, type SortKey, filterInspections, sortInspections, toCsv } from '../lib/inspections'

type Props = { records: Inspection[]; openRecord: (record: Inspection) => void }

export function History({ records, openRecord }: Props) {
  const [query, setQuery] = useState('')
  const [severity, setSeverity] = useState('All')
  const [sort, setSort] = useState<SortKey>('newest')
  const visible = useMemo(() => sortInspections(filterInspections(records, query, severity), sort), [records, query, severity, sort])
  const filtered = visible.length !== records.length

  const exportCsv = () => {
    const stamp = new Date().toISOString().slice(0, 10)
    saveBlob(new Blob([toCsv(visible)], { type: 'text/csv;charset=utf-8' }), `roadguard-inspections-${stamp}.csv`)
  }

  return (
    <>
      <section className="page-intro">
        <div>
          <div className="eyebrow">RECORDS / ARCHIVE</div>
          <h1>Inspection history<span>.</span></h1>
          <p>Search, filter, sort and export every stored inspection.</p>
        </div>
        <div className="intro-actions">
          <button className="secondary-btn" onClick={exportCsv} disabled={visible.length === 0}>
            <Download size={16} /> Export CSV{filtered && visible.length > 0 ? ` (${visible.length})` : ''}
          </button>
        </div>
      </section>
      <section className="panel history-panel">
        <div className="filter-row">
          <label className="search-field">
            <Search size={17} />
            <input type="search" placeholder="Search by ID, damage type, severity or date" aria-label="Search inspections" value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <select className="select-btn" aria-label="Filter by severity" value={severity} onChange={(event) => setSeverity(event.target.value)}>
            <option value="All">All severities</option>
            {SEVERITIES.map((level) => <option key={level} value={level}>{level}</option>)}
          </select>
          <select className="select-btn" aria-label="Sort inspections" value={sort} onChange={(event) => setSort(event.target.value as SortKey)}>
            {Object.entries(SORT_OPTIONS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </div>
        <p className="result-count" role="status">Showing {visible.length} of {records.length} inspections</p>
        <InspectionTable
          records={visible}
          openRecord={openRecord}
          emptyMessage={records.length === 0 ? undefined : 'No inspections match the current search and filter.'}
        />
      </section>
    </>
  )
}
