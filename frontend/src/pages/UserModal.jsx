import { useEffect, useState } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { apiFetch } from '../hooks/useApi'
import { Badge, Loading, ChartTooltip } from '../components/shared'

const SPEDIA_FEATURES = { event_count: 'Events in closed hour', command_events: 'Command events', session_events: 'Session events', file_events: 'File events', http_events: 'HTTP events', email_events: 'Email events', device_events: 'Device events', unique_hosts: 'Observed hosts', prior_events_mean_7d: 'Prior 7-day observed-hour average', prior_observed_windows_7d: 'Prior observed hours', volume_deviation: 'Volume deviation' }
const COMPONENT_LABELS = { if: 'Isolation Forest', pca: 'PCA reconstruction', graph: 'Host novelty', neural: 'Neural reconstruction', supervised: 'Supervised model' }


export default function UserModal({ userId, onClose, onViewGraph }) {
  const [data,setData] = useState(null)
  const [loading,setLoading] = useState(true)
  const [error,setError] = useState('')
  useEffect(() => {
    let active = true
    Promise.resolve().then(() => { if (active) { setLoading(true); setError('') } }).then(() => apiFetch(`/api/users/${encodeURIComponent(userId)}`)).then(d => { if (active) setData(d) })
      .catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [userId])
  const latest = data?.daily_scores?.at(-1)
  const explanation = latest?.explanation || {}
  const evidenceIds = explanation.evidence_record_ids || []
  return <div className="overlay" onClick={e => e.target === e.currentTarget && onClose()}><div className="modal" style={{ width: 'min(980px,96vw)' }}>
    <div className="modal-h"><div><div className="modal-title">Source account</div><code className="mono">{userId}</code><p>Account ID · display name not supplied by this dataset</p></div><button className="btn" onClick={onClose}>Close dossier</button></div>
    <div className="modal-b">{loading ? <Loading /> : error ? <p role="alert">{error}</p> : data && <>
      <Badge tier={data.risk_tier} /><button className="btn" onClick={() => onViewGraph?.(userId)}>View Graph</button>
      <p>Department and employee role are unavailable. Accounts may include services and machines. Event categories depend on source telemetry.</p>
      <div className="feature-grid"><div className="feature-panel">Peak index: {data.max_risk_score?.toFixed(1)}</div><div className="feature-panel">Average index: {data.avg_risk_score?.toFixed(1)}</div><div className="feature-panel">Observed hosts: {data.graph_connections_count}</div></div>
      <div className="card gap16"><div className="card-h">Observed-window risk history</div><div className="card-b"><ResponsiveContainer width="100%" height={220}>
        <AreaChart data={data.daily_scores}><XAxis dataKey="day" /><YAxis domain={[0,100]} /><Tooltip content={<ChartTooltip />} /><Area dataKey="risk_score" name="Risk index" stroke="var(--blue)" fill="var(--blue)" /></AreaChart>
      </ResponsiveContainer></div></div>
      <p>{data.observation_scope}</p>
      <h3>Latest observed window: {latest?.day ?? 'Unavailable'}</h3>
      <div className="info-grid">{Object.entries(SPEDIA_FEATURES).map(([key,label]) => <div className="info-cell" key={key}><div className="info-l">{label}</div><div className="info-v">{latest?.[key]?.toFixed(3) ?? 'Unavailable'}</div></div>)}</div>
      <h3>Anomaly evidence</h3><p>Comparisons describe unusual behavior. They are heuristic evidence, not exact feature attributions or proof of intent.</p>
      {explanation.limitation && <div className="callout">{explanation.limitation}</div>}
      <div className="info-grid">
        {[
          ['Observed events', explanation.event_count],
          ['Prior 7-day observed-hour mean', explanation.prior_7d_observed_window_mean],
          ['History windows', explanation.history_windows],
          ['Volume deviation', explanation.volume_deviation],
        ].map(([label, value]) => <div className="info-cell" key={label}><div className="info-l">{label}</div><div className="info-v">{typeof value === 'number' ? value.toFixed(3) : value ?? 'Unavailable'}</div></div>)}
      </div>
      {explanation.component_indices && <><h4>Model component indices</h4><div className="info-grid">
        {Object.entries(explanation.component_indices).map(([key, value]) => <div className="info-cell" key={key}><div className="info-l">{COMPONENT_LABELS[key] || key}</div><div className="info-v">{typeof value === 'number' ? value.toFixed(3) : value}</div></div>)}
      </div></>}
      <details style={{ marginTop: 16 }}><summary>Evidence record IDs ({evidenceIds.length})</summary>
        {evidenceIds.length ? <ul>{evidenceIds.map(id => <li key={id}><code className="mono">{id}</code></li>)}</ul> : <p>No source record IDs supplied.</p>}
      </details>
      <details style={{ marginTop: 10 }}><summary>Technical explanation</summary>
        <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(explanation, null, 2)}</pre>
      </details>
      <h3>Alert history</h3>{data.alerts.length ? data.alerts.map(a => <div key={a.alert_id} className="signal-card"><Badge tier={a.risk_tier} /> {a.timestamp} · {a.risk_score.toFixed(1)} · {a.status}</div>) : <p>No alerts for this model.</p>}
    </>}</div>
  </div></div>
}
