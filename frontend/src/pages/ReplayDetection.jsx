import { useState, useEffect, useRef, useLayoutEffect } from 'react'
import { apiFetch, useApi } from '../hooks/useApi'

export default function ReplayDetection() {
  const [mode, setMode] = useState('realistic')
  const { data: info, error } = useApi(`/api/replay?mode=${mode}`)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(100)
  const [clock, setClock] = useState(null)
  const [finished, setFinished] = useState(false)
  const [recent, setRecent] = useState([])
  const [played, setPlayed] = useState(0)
  const [page, setPage] = useState(0)
  const [runtime, setRuntime] = useState(null)
  const receivedAt = useRef(0)
  const modeChanged = useRef(false)
  const [run, setRun] = useState(null)
  const [truth, setTruth] = useState(null)
  const [evidence, setEvidence] = useState({})
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  useEffect(() => {
    let cancelled = false
    const id = localStorage.getItem('tracely-replay-run')
    if (id) apiFetch(`/api/replay/runs/${id}`).then(data => {
      if (cancelled || modeChanged.current) return
      setRun(data); setMode(data.mode || 'analysis')
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])
  async function detect() {
    setBusy(true); setFailure(''); setTruth(null)
    try {
      setPlaying(false); setClock(null); setFinished(false); setRecent([]); setPlayed(0); setPage(0)
      const start = performance.now()
      const result = await apiFetch('/api/replay/detect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }) })
      localStorage.setItem('tracely-replay-run', result.run_id)
      const data = await apiFetch(`/api/replay/runs/${result.run_id}`)
      receivedAt.current = performance.now()
      setRuntime({ request_ms: receivedAt.current - start, backend: result.timings, reused: result.reused })
      setRun(data)
    } catch (e) { setFailure(e.message) }
    finally { setBusy(false) }
  }
  useLayoutEffect(() => {
    if (receivedAt.current && run) setRuntime(current => ({ ...current, react_commit_ms: performance.now() - receivedAt.current }))
  }, [run])
  useEffect(() => {
    if (!playing || !run) return
    let cancelled = false
    async function play() {
      setRecent([]); setPlayed(0); setClock(null); setFinished(false)
      let offset = 0
      try {
        do {
          const batch = await apiFetch(`/api/replay/runs/${run.run_id}/events?offset=${offset}&limit=500`)
          if (cancelled) return
          for (let i = 0; i < batch.events.length; i += speed) {
            await new Promise(resolve => setTimeout(resolve, 100))
            if (cancelled) return
            const chunk = batch.events.slice(i, i + speed)
            setRecent(current => [...current, ...chunk].slice(-25))
            setPlayed(current => current + chunk.length)
            setClock(chunk[chunk.length - 1].time)
          }
          offset = batch.next_offset
        } while (offset !== null && !cancelled)
        if (!cancelled) { setFinished(true); setPlaying(false) }
      } catch (e) { if (!cancelled) { setFailure(e.message); setPlaying(false) } }
    }
    play()
    return () => { cancelled = true }
  }, [playing, run, speed])
  function changeMode(value) {
    modeChanged.current = true
    setMode(value); setRun(null); setTruth(null); setEvidence({}); setPlaying(false)
    setRecent([]); setClock(null); setFinished(false); setPage(0); setRuntime(null)
    localStorage.removeItem('tracely-replay-run')
  }
  async function showEvents(p) {
    try {
      const data = await apiFetch(`/api/replay/runs/${run.run_id}/events?window_id=${encodeURIComponent(p.window_id)}`)
      setEvidence(current => ({ ...current, [p.window_id]: data.events }))
    } catch (e) { setFailure(e.message) }
  }
  async function reveal() {
    try { setTruth(await apiFetch(`/api/replay/runs/${run.run_id}/ground-truth`)) }
    catch (e) { setFailure(e.message) }
  }
  async function updateAlert(p) {
    setBusy(true)
    try {
      await apiFetch(`/api/threats/${p.alert_id}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'IN_PROGRESS', version: p.alert_version }) })
      setRun(await apiFetch(`/api/replay/runs/${run.run_id}`))
    } catch (e) { setFailure(e.message) }
    finally { setBusy(false) }
  }
  const visible = (run?.predictions || []).filter(p => mode === 'analysis' || finished || (clock && new Date(clock).getTime() >= new Date(p.window_start.replace(' ', 'T')).getTime() + 3600000))
  const labels = Object.fromEntries((truth?.windows || []).map(w => [w.window_id, w]))
  return <div className="page">
    <header className="replay-header">
      <div><div className="replay-kicker">FROZEN SPEDIA V2 / HISTORICAL INFERENCE</div><h1>Replay Detection</h1><p>Review closed-hour predictions against preserved event history. This is not live traffic.</p></div>
      <label className="replay-mode-control">Replay mode<select aria-label="Replay mode" value={mode} disabled={busy} onChange={e => changeMode(e.target.value)}><option value="realistic">Realistic Event Replay</option><option value="analysis">Detection Analysis</option></select></label>
    </header>
    {(error || failure) && <div role="alert" className="callout">{failure || error}</div>}
    {info && <>
      <section className="replay-context" aria-label="Replay dataset context">
        <div className="replay-context-count"><strong>{info.events} source events · {info.windows} user-hours</strong><span>{mode === 'realistic' ? 'Chronological held-out coverage' : 'Outcome-selected teaching sample'}</span></div>
        <div className="replay-context-item"><span>Frozen model</span><code title={info.model_version}>{info.model_version}</code></div>
        <div className="replay-context-item"><span>Alert threshold</span><strong>{info.threshold?.toFixed(4)} <small>index</small></strong></div>
      </section>
      <p className="replay-scope-note">{mode === 'realistic' ? info.selection : 'Outcome-selected examples demonstrate true positives, false negatives, false positives and true negatives. This sample cannot estimate performance.'}</p>
      <details className="replay-history-note"><summary>History and scoring scope</summary><p>{info.history}</p></details>
    </>}
    <section className="replay-runbar">
      <div className="replay-run-actions">
        <button className="btn btn-primary" onClick={detect} disabled={busy || !info || info.mode !== mode}>{busy ? 'Scoring…' : 'Run frozen detection'}</button>
        {run && mode === 'analysis' && <button className="btn" onClick={reveal}>Reveal separate ground truth</button>}
      </div>
      {runtime && <div className="replay-runtime" data-testid="replay-runtime"><span>Request {runtime.request_ms?.toFixed(1)} ms</span><span>UI render {runtime.react_commit_ms?.toFixed(1)} ms</span><span>{runtime.reused ? 'Persisted result reused' : 'Fresh inference'}</span><details><summary>Timing details</summary><p>{Object.entries(runtime.backend || {}).map(([key, value]) => `${key}: ${value.toFixed(1)} ms`).join(' · ')}</p></details></div>}
    </section>
    {run && mode === 'realistic' && <section className="replay-playback">
      <div className="replay-playback-top"><div><div className="replay-kicker">CHRONOLOGICAL PLAYBACK</div><h2>Event stream</h2><p>Predictions appear when each historical hour closes.</p></div>
        <div className="replay-playback-controls"><label>Events per tick<select aria-label="Events per tick" value={speed} disabled={playing} onChange={e => setSpeed(Number(e.target.value))}><option value={1}>1</option><option value={25}>25</option><option value={100}>100</option></select></label><button className={`btn${playing ? '' : ' btn-primary'}`} onClick={() => setPlaying(value => !value)}>{playing ? 'Stop playback' : 'Start historical playback'}</button></div>
      </div>
      <div className="replay-progress-meta"><strong>{played.toLocaleString()} / {info?.events.toLocaleString()} events</strong><span>Historical clock: {clock || 'Awaiting playback'}</span><span>{finished ? 'Complete; final hour closed' : `${visible.length} closed hours`}</span></div>
      <div className="replay-progress-track"><div style={{ width: `${info?.events ? Math.min(100, played / info.events * 100) : 0}%` }} /></div>
      <div className="replay-live-events"><div className="replay-live-heading">Most recent source events <span>{recent.length} shown</span></div>
        {recent.length ? <ol>{recent.slice().reverse().map(event => <li key={event.source_record_id}><time>{event.time}</time><code>{event.user}</code><span>{event.Activity} / {event.Action}</span><small>Host {event.host}</small></li>)}</ol> : <p>Start playback to follow the historical event stream.</p>}
      </div>
    </section>}
    {truth && <section className="replay-truth-summary"><div><div className="replay-kicker">SEPARATE ANNOTATIONS</div><h2>Ground truth revealed</h2><p>{truth.warning}</p></div><div className="replay-outcome-counts">{['TP','FN','FP','TN'].map(outcome => <div key={outcome}><strong>{outcome}</strong><span>{truth.windows.filter(w => w.example_outcome === outcome).length}</span></div>)}</div></section>}
    {run && <section className="replay-predictions"><div className="replay-predictions-heading"><div><div className="replay-kicker">Persisted run: frozen inference</div><h2>Closed-hour predictions</h2><p>Alert status survives reload. Risk scores are anomaly indices, not probabilities.</p></div><details className="replay-run-id"><summary>Run reference</summary><code>{run.run_id}</code></details></div>
      <div className="replay-table-wrap"><table className="tbl replay-table"><thead><tr><th>User / closed hour</th><th>Events</th><th>Risk index</th><th>Decision</th><th>Persisted alert</th><th>Ground truth</th><th>Behavioral evidence</th></tr></thead><tbody>
        {visible.slice(page * 30, (page + 1) * 30).map(p => <tr key={p.window_id}>
          <td>{p.user}<br/><small>{p.window_start} (timezone unspecified)</small></td><td>{p.events}</td>
          <td>{p.risk_score.toFixed(2)}<br/>{p.risk_tier}</td><td>{p.prediction ? 'Flagged' : 'Below threshold'}</td>
          <td>{p.alert_status || 'No alert'}{p.alert_status === 'OPEN' && <button className="btn" disabled={busy} onClick={() => updateAlert(p)}>Investigate</button>}</td>
          <td>{labels[p.window_id] ? `${labels[p.window_id].label ? 'Attack annotation' : 'Non-attack annotation'} · ${labels[p.window_id].example_outcome}` : 'Hidden'}{labels[p.window_id]?.miss_explanation && <p>{labels[p.window_id].miss_explanation}</p>}</td>
          <td>Events: {p.explanation.event_count}; prior observed-hour mean: {p.explanation.prior_7d_observed_window_mean?.toFixed(2)}; new hosts: {p.explanation.new_hosts}.<br/><small>IF {p.components.if?.toFixed(1)} · reconstruction {p.components.neural?.toFixed(1)} · host novelty {p.components.graph?.toFixed(1)}. Comparisons, not exact model attribution.</small><details onToggle={e => { if (e.currentTarget.open && !evidence[p.window_id]) showEvents(p) }}><summary>Source event evidence</summary>{evidence[p.window_id]?.map(event => <p key={event.source_record_id}><code>{event.source_record_id}</code> · {event.time} · {event.Activity} · {event.Action} · observed host {event.host}</p>)}</details></td>
        </tr>)}
      </tbody></table></div><div className="replay-table-footer"><span>{visible.length} closed-hour predictions</span><div><button className="btn" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Previous</button><span>Page {page + 1}</span><button className="btn" disabled={(page + 1) * 30 >= visible.length} onClick={() => setPage(p => p + 1)}>Next</button></div></div></section>}
  </div>
}
