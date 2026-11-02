import { useState, useEffect } from 'react'
import { CheckCircle2, Database, FileText, RefreshCw, ShieldCheck, Upload } from 'lucide-react'
import { apiFetch, useApi } from '../hooks/useApi'

export default function NewDataInference() {
  const { data: context, error, refetch } = useApi('/api/inference/context')
  const { data: history, refetch: refreshHistory } = useApi('/api/inference/runs')
  const [file, setFile] = useState(null)
  const [end, setEnd] = useState('')
  const [provenance, setProvenance] = useState('')
  const [complete, setComplete] = useState(false)
  const [sourceKind, setSourceKind] = useState('user-supplied-unverified')
  const [run, setRun] = useState(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const id = localStorage.getItem('tracely-import-run')
    if (id) apiFetch(`/api/inference/runs/${id}`).then(setRun).catch(() => {})
  }, [])
  async function openRun(id) {
    try { setRun(await apiFetch(`/api/inference/runs/${id}`)); localStorage.setItem('tracely-import-run', id) }
    catch (e) { setMessage(e.message) }
  }
  async function upload(e) {
    e.preventDefault(); setBusy(true); setMessage('')
    const form = new FormData()
    form.set('file', file); form.set('context_token', context.context_token)
    form.set('coverage_start', context.next_coverage_start); form.set('coverage_end', end)
    form.set('complete_hours', String(complete)); form.set('profile', 'spedia-v2-native')
    form.set('source_kind', sourceKind); form.set('provenance', provenance)
    try {
      const response = await apiFetch('/api/inference/import', { method: 'POST', body: form })
      await openRun(response.run_id); await refetch(); await refreshHistory()
      setMessage(response.reused ? 'Existing import restored; no duplicate alerts.' : 'Raw events converted to features and scored with the frozen model. Predictions persisted.')
    } catch (err) { setMessage(err.message) }
    finally { setBusy(false) }
  }
  async function investigate(p) {
    setBusy(true)
    try {
      await apiFetch(`/api/inference/alerts/${p.alert_id}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'IN_PROGRESS', version: p.alert_version }) })
      await openRun(run.run_id)
    } catch (e) { setMessage(e.message) }
    finally { setBusy(false) }
  }
  return <div className="page inference-page">
    <header className="inference-heading"><div><div className="inference-kicker">FROZEN MODEL / INFERENCE</div><h1>New Data Inference</h1><p>Score compatible activity against verified history. This workflow does not train or change the model.</p></div>{context && <span className="inference-state"><span/>Ready to score</span>}</header>
    <div className="callout inference-caveat">Imported predictions are separate from benchmark evaluation. Labels are not accepted; source provenance and telemetry completeness remain operator declarations.</div>
    {error && <p role="alert">{error}</p>}
    {context && <><div className="inference-meta"><div className="inference-meta-item"><span>Frozen model</span><code title={context.model_version}>{context.model_version}</code></div><div className="inference-meta-item"><span>Next coverage start</span><strong>{context.next_coverage_start}</strong></div><div className="inference-meta-item"><span>Alert threshold</span><strong>{context.threshold.toFixed(4)} <small>index</small></strong></div></div>
      <div className="inference-layout"><form className="inference-form" onSubmit={upload}>
        <div className="inference-section-head"><span className="inference-step">01</span><div><h2>Register activity</h2><p>Declare source, coverage, and compatibility before scoring.</p></div></div>
        <div className="inference-fields">
          <label>Source kind<select className="search" aria-label="Source kind" value={sourceKind} onChange={e => setSourceKind(e.target.value)}><option value="user-supplied-unverified">User-supplied, provenance unverified</option>{context.allow_test_fixtures && <option value="engineering-test-fixture">Engineering test fixture (not evaluation)</option>}</select></label>
          <label>Coverage end (exclusive, complete hour)<input className="search" aria-label="Coverage end" value={end} onChange={e => setEnd(e.target.value)} placeholder="2025-03-30 21:00:00" required /></label>
          <label className="inference-file-field">Raw activity CSV<span className="inference-file-control"><FileText size={17}/><span>{file?.name || 'Choose a compatible CSV file'}</span><input aria-label="Raw activity CSV" type="file" accept=".csv,text/csv" required onChange={e => setFile(e.target.files[0])}/></span><small>Up to {context.max_events.toLocaleString()} events / {Math.round(context.max_bytes / 1024)} KiB</small></label>
          <label className="inference-provenance">Source and compatibility description<textarea className="search" aria-label="Source and compatibility description" value={provenance} onChange={e => setProvenance(e.target.value)} minLength={10} maxLength={1000} placeholder="Describe the source, collection scope, and how its event semantics and units match the registered stream." required /></label>
        </div>
        <label className="inference-confirm"><input type="checkbox" checked={complete} required onChange={e => setComplete(e.target.checked)}/><span><strong>Confirm complete telemetry</strong><small>All users are covered for the declared hours, with the same account/host namespace, compatible activity semantics, and native numeric units.</small></span></label>
        <div className="inference-form-footer"><span>Coverage starts at <strong>{context.next_coverage_start}</strong></span><button className="btn btn-primary" type="submit" disabled={busy || !file || !complete}><Upload size={14}/>{busy ? 'Scoring activity…' : 'Score raw CSV'}</button></div>
      </form>
      <aside className="inference-context"><div className="inference-section-head"><span className="inference-step"><ShieldCheck size={16}/></span><div><h2>Compatibility checks</h2><p>Required for a valid historical comparison.</p></div></div>
        <ul className="inference-check-list"><li><CheckCircle2 size={15}/><span>1–24 aligned, complete hours</span></li><li><CheckCircle2 size={15}/><span>Known account IDs and continuous history</span></li><li><CheckCircle2 size={15}/><span>Native SPEDIA action vocabulary and units</span></li></ul>
        <details className="inference-details"><summary><Database size={14}/>Known account IDs<span>{context.known_users.length}</span></summary><ul className="inference-id-list">{context.known_users.map(id => <li key={id}><code>{id}</code></li>)}</ul><p>Unknown accounts or gaps in history are rejected.</p></details>
        <details className="inference-details"><summary><FileText size={14}/>Required CSV schema</summary><ul className="inference-schema">{context.required_columns.map(column => <li key={column}><code>{column}</code></li>)}</ul><p>{context.source_policy}</p><p>Columns must be present even when a value is inapplicable. Native source units must match SPEDIA.</p><p><strong>Supported actions:</strong> {Object.entries(context.actions).map(([key, values]) => `${key}: ${values.join(', ')}`).join(' · ')}</p></details>
        <div className="inference-history"><div className="inference-history-heading"><span>Previous imports</span><button className="icon-btn" type="button" title="Refresh imports" aria-label="Refresh imports" onClick={refreshHistory}><RefreshCw size={14}/></button></div>{history?.runs?.length ? history.runs.map(r => <button className="inference-run-link" type="button" key={r.run_id} onClick={() => openRun(r.run_id)}><span>{r.coverage_start} → {r.coverage_end}</span><small>{r.windows} windows · {r.source_kind}</small></button>) : <p>No previous imports in this stream.</p>}</div>
      </aside></div></>}
    {message && <p role="status">{message}</p>}
    {history?.runs?.length > 0 && <details><summary>Persisted imports</summary>{history.runs.map(r => <p key={r.run_id}><button className="btn" onClick={() => openRun(r.run_id)}>{r.coverage_start} → {r.coverage_end} · {r.windows} windows · {r.source_kind}</button></p>)}</details>}
    {run && <><h3>Persisted new-data predictions</h3><p>Import run ID: <code>{run.run_id}</code> · {run.provenance.source_kind}</p><p>{run.provenance.description}</p><div style={{overflowX:'auto'}}><table className="tbl"><thead><tr><th>Account ID / hour</th><th>Events</th><th>Risk index</th><th>Decision</th><th>Alert</th><th>Observed behavior</th></tr></thead><tbody>{run.predictions.map(p => <tr key={p.window_id}><td><code className="mono">{p.user}</code><br/>{p.window_start}</td><td>{p.events}</td><td>{p.risk_score.toFixed(4)} · {p.risk_tier}</td><td>{p.prediction ? 'Flagged' : 'Below threshold'}</td><td>{p.alert_status || 'No alert'}{p.alert_status === 'OPEN' && <button className="btn" onClick={() => investigate(p)} disabled={busy}>Investigate import</button>}</td><td>Prior observed-hour mean {p.explanation.prior_7d_observed_window_mean.toFixed(2)}; deviation {p.explanation.volume_deviation.toFixed(2)}; new hosts {p.explanation.new_hosts}.<br/>IF {(p.components.if_score ?? p.components.if)?.toFixed(2)} · reconstruction {(p.components.neural_score ?? p.components.neural)?.toFixed(2)} · novelty {(p.components.graph == null ? 'not used by this model' : p.components.graph.toFixed(2))}<details><summary>Evidence record IDs ({p.explanation.evidence_record_ids.length})</summary><ul>{p.explanation.evidence_record_ids.map(id => <li key={id}><code className="mono">{id}</code></li>)}</ul></details></td></tr>)}</tbody></table></div><p>These indices indicate unusual behavior, not a probability or proof of malicious intent. Imported events have no evaluated attack labels.</p></>}
  </div>
}
