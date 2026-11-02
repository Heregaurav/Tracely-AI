import { useState } from 'react'
import { Download, ExternalLink, RefreshCw } from 'lucide-react'
import { useApi, apiFetch } from '../hooks/useApi'
import { Loading, Badge } from '../components/shared'

const COMPARISON_METRICS = ['pr_auc_average_precision', 'roc_auc', 'precision', 'recall', 'f1']

export default function Reports() {
  const { data: metrics, loading, error, refetch } = useApi('/api/model-metrics')
  const { data: source } = useApi('/api/data-sources')
  const [message, setMessage] = useState('')
  const exportReport = async () => {
    try {
      const result = await apiFetch('/api/export?limit=500')
      const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }))
      const link = Object.assign(document.createElement('a'), { href: url, download: 'tracely-scores.json' })
      link.click(); URL.revokeObjectURL(url)
    } catch (err) { setMessage(err.message) }
  }
  const format = value => value == null ? 'Unavailable' : typeof value === 'number' ? value.toFixed(3) : String(value)
  const selected = metrics?.held_out_metrics?.[metrics.active_configuration]
  const formatMetric = value => value == null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`
  return <div className="page report-page">
    <header className="report-heading"><div><div className="report-kicker">MODEL GOVERNANCE / SPEDIA V2</div><h1>Model report</h1><p>Frozen evaluation, active configuration, and source provenance.</p></div><div className="report-actions"><button className="btn" onClick={refetch}><RefreshCw size={14}/>Refresh report</button><button className="btn btn-primary" onClick={exportReport}><Download size={14}/>Export scores</button></div></header>
    {(error || message) && <div role="alert" className="callout">{error || message}</div>}
    {loading ? <Loading /> : metrics && <>
      {metrics.is_fixture && <div role="alert" className="callout report-fixture-warning"><strong>UNIT TEST FIXTURE ONLY.</strong> These metrics are not real-world evaluation results.</div>}
      <section className="report-active-summary" aria-label="Active held-out result">
        <div className="report-active-heading"><div><span className="report-kicker">ACTIVE FROZEN CONFIGURATION</span><h2>{metrics.active_configuration?.replaceAll('_', ' ')}</h2></div><span className="report-scope">Held-out set · {selected?.windows ?? '—'} windows · {selected?.positive_windows ?? '—'} annotated positive</span></div>
        <div className="report-metrics">{[['Precision', selected?.precision, 'var(--green)'], ['Recall', selected?.recall, 'var(--orange)'], ['F1', selected?.f1, 'var(--cyan)'], ['PR average precision', selected?.pr_auc_average_precision, 'var(--blue)'], ['Alerts', selected?.alert_count, 'var(--yellow)']].map(([label, value, color]) => <div className="report-metric" key={label}><span>{label}</span><strong style={{ color }}>{label === 'Alerts' ? value ?? 'Unavailable' : formatMetric(value)}</strong></div>)}</div>
        <p className="report-caveat">Held-out result for the frozen selection. Scores are not probabilities; this controlled mixed-origin dataset does not establish independent deployment performance.</p>
      </section>
      <div className="g2">
        <div className="card"><div className="card-h"><span className="card-t">Active configuration</span></div><div className="card-b">
          {Object.entries({ Version: metrics.version, Configuration: metrics.active_configuration,
            Weights: Object.entries(metrics.weights || {}).map(([key, value]) => `${key}: ${(value * 100).toFixed(0)}%`).join(' · '), Reconstruction: metrics.models?.reconstruction,
            Neural: metrics.models?.neural, Features: metrics.contract?.features.length,
            Scaling: metrics.scaling, Scope: metrics.evaluation_scope }).map(([label,value]) =>
            <p key={label}><strong>{label}:</strong> {format(value)}</p>)}
          <p>Indices range from 0 to 100. They do not estimate the probability of malicious activity.</p>
          {metrics.is_fixture && <p role="alert">UNIT TEST FIXTURE ONLY. These metrics are not real-world evaluation results.</p>}
        </div></div>
        <div className="card"><div className="card-h"><span className="card-t">Data source</span></div><div className="card-b">
          <p>{source?.dataset_id}</p><p>Origin: {source?.authenticity}</p>
          <p>SHA-256: <span style={{ overflowWrap: 'anywhere' }}>{source?.sha256}</span></p>
          <p>Selection: {source?.selection_policy}</p><p>{source?.observation_scope}</p>{(source?.actual_download_url || source?.source_url) && <a className="report-source-link" href={source.actual_download_url || source.source_url} target="_blank" rel="noreferrer">Open source reference <ExternalLink size={13}/></a>}
          <p>Annotation scope: {source?.label_reconciliation?.coverage || 'See the preserved model evaluation'}</p>
          <p>{source?.limitations}</p>
        </div></div>
      </div>
      <div className="card gap16 report-comparison"><div className="card-h"><span className="card-t">Held-out comparison</span></div><div className="card-b">
        <p>Selection uses validation data: {metrics.selection_policy}. Metrics use supplied research annotations at user-hour level.</p>
        <div className="report-split-list">{Object.entries(metrics.splits || {}).map(([name, split]) => <div key={name}><strong>{name}</strong><span>{split.min_time} – {split.max_time}</span><small>{split.windows} windows · {split.events} events</small></div>)}</div>
        <div className="report-table-wrap"><table className="tbl report-table"><thead><tr><th>Model</th><th>Windows</th><th>PR-AP</th><th>ROC-AUC</th><th>Precision</th><th>Recall</th><th>F1</th><th>Alerts</th></tr></thead>
          <tbody>{Object.entries(metrics.held_out_metrics || {}).map(([name,m]) => <tr key={name} className={name === metrics.active_configuration ? 'report-active-row' : ''}>
            <td><strong>{name.replaceAll('_', ' ')}</strong>{name === metrics.active_configuration && <span className="report-active-tag">ACTIVE</span>}</td><td>{m.windows ?? '—'}</td>{COMPARISON_METRICS.map(key => <td key={key}>{formatMetric(m[key])}</td>)}<td>{m.alert_count ?? 'Unavailable'}</td>
          </tr>)}</tbody></table>
        </div><p>PR-AP is average precision. Undefined or unsupported metrics remain unavailable. Full report metadata includes confusion matrices and workload.</p>
      </div></div>
      <div className="card gap16"><div className="card-h"><span className="card-t">Calibration</span></div><div className="card-b">
        <p>{metrics.calibration?.component_scale}. Reference: {metrics.calibration?.reference}.</p>
        {['NORMAL','LOW','MEDIUM','HIGH','CRITICAL'].map((tier,i) => <p key={tier}><Badge tier={tier} /> {i === 0 ? `< ${format(metrics.calibration?.tier_thresholds?.[0])}` : i === 4 ? `≥ ${format(metrics.calibration?.tier_thresholds?.[3])}` : `${format(metrics.calibration?.tier_thresholds?.[i-1])} ≤ index < ${format(metrics.calibration?.tier_thresholds?.[i])}`} </p>)}
      </div></div>
      <div className="card"><div className="card-h"><span className="card-t">Reports and exports</span></div><div className="card-b">
        <p role="status">{message}</p>
        <p>This experiment is frozen. Replay performs inference only. A new training study requires a new untouched evaluation set.</p>
        {metrics.limitations?.map(item => <p key={item}>{item}</p>)}
      </div></div>
    </>}
  </div>
}
