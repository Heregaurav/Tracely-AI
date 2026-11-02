import { useState, useMemo } from 'react'
import { useApi, apiFetch } from '../hooks/useApi'
import { Badge, Loading, Empty, ScoreDonut } from '../components/shared'
import { CheckCircle2, Download, LoaderCircle, PlayCircle, Siren, X } from 'lucide-react'

const TC = { CRITICAL:'var(--red)', HIGH:'var(--orange)', MEDIUM:'var(--yellow)', LOW:'var(--cyan)', NORMAL:'var(--green)' }
const TIERS = ['ALL','CRITICAL','HIGH','MEDIUM','LOW','NORMAL']
const STATUS_META = {
  OPEN: { label: 'Open', accent: 'var(--orange)', bg: 'rgba(251,146,60,.15)' },
  IN_PROGRESS: { label: 'In Progress', accent: 'var(--blue)', bg: 'rgba(91,141,246,.15)' },
  RESOLVED: { label: 'Resolved', accent: 'var(--green)', bg: 'rgba(52,211,153,.12)' },
}

function StatusBadge({ status = 'OPEN' }) {
  const meta = STATUS_META[status] || STATUS_META.OPEN
  return (
    <span style={{
      padding:'3px 10px',
      borderRadius:20,
      fontSize:10,
      fontFamily:"'JetBrains Mono',monospace",
      fontWeight:600,
      background:meta.bg,
      color:meta.accent,
      border:`1px solid ${meta.accent}33`,
    }}>
      {meta.label}
    </span>
  )
}

function StatusActions({ alert, busyId, onChange, compact = false }) {
  const disabled = busyId === alert.alert_id
  const actions = [
    { key: 'OPEN', label: 'Open', Icon: Siren },
    { key: 'IN_PROGRESS', label: 'In Progress', Icon: PlayCircle },
    { key: 'RESOLVED', label: 'Resolved', Icon: CheckCircle2 },
  ]
  return (
    <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
      {actions.map(({ key, label, Icon }) => {
        const active = (alert.status || 'OPEN') === key
        const meta = STATUS_META[key]
        return (
          <button
            key={key}
            type="button"
            className={`btn${compact ? ' btn-sm' : ''}`}
            disabled={disabled}
            onClick={(e) => {
              e.stopPropagation()
              onChange(alert.alert_id, key)
            }}
            style={{
              background: active ? meta.bg : 'transparent',
              borderColor: active ? `${meta.accent}55` : 'var(--line2)',
              color: active ? meta.accent : 'var(--t2)',
              opacity: disabled ? 0.7 : 1,
            }}
          >
            {disabled ? <LoaderCircle size={12} style={{ animation:'rot .7s linear infinite' }} /> : <Icon size={12} />}
            {label}
          </button>
        )
      })}
    </div>
  )
}

function AlertEvidence({ explanation = {} }) {
  const evidenceIds = Array.isArray(explanation.evidence_record_ids) ? explanation.evidence_record_ids : []
  const metrics = [
    ['Events in observed hour', explanation.event_count],
    ['Prior 7-day hourly average', explanation.prior_7d_observed_window_mean],
    ['Volume deviation', explanation.volume_deviation],
    ['New hosts', explanation.new_hosts],
    ['History windows', explanation.history_windows],
  ]
  const format = value => typeof value === 'number' ? value.toFixed(2) : value ?? 'Unavailable'
  const componentLabels = {
    if: 'Isolation Forest',
    neural: 'Neural reconstruction',
    graph: 'Host novelty',
    pca: 'PCA comparison',
    supervised: 'Supervised model',
  }
  const componentIndices = Object.fromEntries(Object.entries(explanation.component_indices || {}).map(([key, value]) => [key.replace(/_score$/, ''), value]))
  const activeSignals = ['if', 'neural', 'graph'].filter(key => componentIndices[key] != null)
  const comparisonSignals = Object.entries(componentIndices).filter(([key]) => !activeSignals.includes(key))
  const shortId = id => id.length > 18 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id

  return (
    <section className="alert-evidence">
      <h3>Behavioral evidence</h3>
      <p>These are model comparison signals, not exact feature attributions or proof of malicious intent.</p>
      {explanation.limitation && <div className="callout alert-evidence-limit">{explanation.limitation}</div>}
      <div className="alert-evidence-stats">
        {metrics.map(([label, value]) => (
          <div className="alert-evidence-stat" key={label}>
            <span>{label}</span>
            <strong>{format(value)}</strong>
          </div>
        ))}
      </div>
      {activeSignals.length > 0 && <div className="alert-signals">
        <div className="alert-signals-heading">Active model signals <span>index · 0–100</span></div>
        {activeSignals.map(key => {
          const value = Number(componentIndices[key])
          return <div className="alert-signal" key={key}>
            <span>{componentLabels[key]}</span>
            <div className="alert-signal-track"><div style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>
            <strong>{format(value)}</strong>
          </div>
        })}
      </div>}
      {comparisonSignals.length > 0 && <details className="alert-evidence-details"><summary>Additional model comparisons ({comparisonSignals.length})</summary><div className="alert-comparison-list">{comparisonSignals.map(([key, value]) => <div key={key}><span>{componentLabels[key] || key}</span><strong>{format(value)}</strong></div>)}</div></details>}
      <details className="alert-evidence-details"><summary>Source evidence IDs ({evidenceIds.length})</summary>
        {evidenceIds.length ? <ul className="alert-evidence-ids">{evidenceIds.map(id => <li key={id} title={id}><code>{shortId(id)}</code></li>)}</ul> : <p>No source record IDs supplied.</p>}
      </details>
      <details className="alert-evidence-details"><summary>Window metadata</summary>
        <dl className="alert-window-metadata"><div><dt>Window start</dt><dd>{explanation.window_start || 'Unavailable'}</dd></div><div><dt>Window unit</dt><dd>{explanation.window_unit || 'Unavailable'}</dd></div><div><dt>Window index</dt><dd>{explanation.window_index ?? 'Unavailable'}</dd></div><div><dt>Relative window</dt><dd>{explanation.relative_day ?? 'Unavailable'}</dd></div></dl>
      </details>
    </section>
  )
}

function AlertModal({ alert, onClose, busyId, onStatusChange }) {
  if (!alert) return null
  const alertReference = alert.alert_id?.slice(0, 12) || 'Unavailable'
  return (
    <div className="overlay" onClick={e => e.target===e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-h">
          <div style={{display:'flex',alignItems:'center',gap:16}}>
            <ScoreDonut score={alert.risk_score||0} size={62}/>
            <div>
              <div className="modal-title">{alert.alert_type?.replace(/_/g, ' ') || 'Anomaly alert'}</div>
              <div style={{fontSize:12,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace",marginTop:3}}>
                Account ID: {alert.user_id || 'Unavailable'}
              </div>
              <div className="mono" title={alert.alert_id}>Alert {alertReference}{alert.alert_id?.length > 12 ? '…' : ''}</div>
              <div style={{marginTop:7}}><Badge tier={alert.risk_tier}/></div>
            </div>
          </div>
          <button className="modal-x" onClick={onClose}><X size={16}/></button>
        </div>
        <div className="modal-b">
          {alert.message && (
            <div style={{background:'var(--bg3)',borderRadius:7,padding:'12px 16px',marginBottom:20,fontSize:13,color:'var(--t2)',borderLeft:`3px solid ${TC[alert.risk_tier]||'#666'}`,lineHeight:1.6}}>
              {alert.message}
            </div>
          )}
          <div className="info-grid">
            {[
              ['Account ID', alert.user_id || 'Unavailable'],
              ['Department', alert.department || 'Unavailable'],
              ['Risk index', alert.risk_score?.toFixed(2)],
              ['IF Score',   alert.if_score!=null ? alert.if_score.toFixed(2) : '—'],
              ['AE Score',   alert.ae_score!=null ? alert.ae_score.toFixed(2)  : '—'],
              ['Alert Type', alert.alert_type?.replace(/_/g,' ')],
              ['Status',     alert.status],
              ['Observation time', alert.timestamp],

            ].map(([k,v]) => (
              <div key={k} className="info-cell">
                <div className="info-l">{k}</div>
                <div className="info-v" style={{fontFamily:['Risk index','IF Score','AE Score','Account ID'].includes(k)?'"JetBrains Mono",monospace':'inherit',overflowWrap:'anywhere'}}>{v}</div>
              </div>
            ))}
          </div>
          <details style={{ marginTop: 16 }}>
            <summary>Technical identifiers</summary>
            <p>Alert ID<br/><code className="mono" style={{ overflowWrap:'anywhere' }}>{alert.alert_id}</code></p>
          </details>
          <AlertEvidence explanation={alert.explanation} />
          <div style={{ marginTop: 18 }}>
            <div className="info-l" style={{ marginBottom: 10 }}>Threat Workflow</div>
            <StatusActions alert={alert} busyId={busyId} onChange={onStatusChange} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Threats({ hour, userId, onNavigate }) {
  const [tier,  setTier]  = useState('ALL')
  const [search,setSearch]= useState(userId || '')
  const [sel,   setSel]   = useState(null)
  const [sc,    setSC]    = useState('risk_score')
  const [asc,   setAsc]   = useState(false)
  const [busyId,setBusyId]= useState(null)
  const [message, setMessage] = useState('')
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')

  const { data, loading, error, refetch } = useApi(
    `/api/threats?limit=50&page=${page}${hour == null ? '' : `&hour=${encodeURIComponent(hour)}`}&sort=${sc === 'relative_day' ? 'time' : 'risk'}${tier === 'ALL' ? '' : `&tier=${tier}`}${statusFilter ? `&status=${statusFilter}` : ''}${search ? `&user_id=${encodeURIComponent(search)}` : ''}`,
    [tier]
  )

  const alerts = useMemo(() => {
    let list = data?.alerts || []
    if (search) {
      const q = search.toLowerCase()
      list = list.filter(a =>
        a.user_id?.toLowerCase().includes(q) ||
        a.department?.toLowerCase().includes(q) ||
        a.alert_id?.toLowerCase().includes(q)
      )
    }
    return [...list].sort((a,b) => {
      const av=a[sc]??'', bv=b[sc]??''
      return asc ? (av>bv?1:-1) : (av<bv?1:-1)
    })
  }, [data, search, sc, asc])

  const sort = col => { if(col===sc) setAsc(a=>!a); else {setSC(col);setAsc(false)} }
  const sortHeader = (col,label) => (
    <th onClick={() => sort(col)}>
      {label}{sc===col?(asc?' ↑':' ↓'):''}
    </th>
  )

  const exportCSV = async () => {
    let rows
    try { rows = (await apiFetch(`/api/export?kind=alerts&limit=500${hour == null ? '' : `&hour=${encodeURIComponent(hour)}`}${tier === 'ALL' ? '' : `&tier=${tier}`}${statusFilter ? `&status=${statusFilter}` : ''}${search ? `&user_id=${encodeURIComponent(search)}` : ''}`)).records } catch (err) { setMessage(err.message); return }
    const cols = ['alert_id','user_id','department','risk_tier','risk_score','alert_type','status','timestamp']
    const csv  = [cols.join(','), ...rows.map(a=>cols.map(c => { let v = String(a[c] ?? ''); if (/^[=+@-]/.test(v)) v = "'" + v; return '"' + v.replaceAll('"', '""') + '"' }).join(','))].join('\n')
    const url  = URL.createObjectURL(new Blob([csv],{type:'text/csv'}))
    Object.assign(document.createElement('a'),{href:url,download:'tracely_ai_alerts.csv'}).click(); URL.revokeObjectURL(url)
  }

  const updateStatus = async (alertId, status) => {
    setMessage('')
    const current = alerts.find(a => a.alert_id === alertId)
    setBusyId(alertId)
    try {
      const response = await apiFetch(`/api/threats/${alertId}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, version: current?.version }),
      })
      if (sel?.alert_id === alertId) setSel(response.alert)
      refetch()
    } catch (err) {
      setMessage(err.message); refetch()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="page">
      {hour != null && <div className="callout hourly-alert-scope"><span>Only alerts from the selected closed hour are shown. Scores and statuses belong to that hour.</span><button className="btn btn-sm" onClick={() => onNavigate?.('hourly', { hour })}>Back to selected hour</button><button className="btn btn-sm" onClick={() => onNavigate?.('threats')}>All historical alerts</button></div>}
      {(error || message) && <p role="alert">{error || message}</p>}
      {sel && <AlertModal alert={sel} onClose={() => setSel(null)} busyId={busyId} onStatusChange={updateStatus} />}

      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:20,flexWrap:'wrap',gap:12}}>
        <div className="sec">
          <div className="sec-t">{hour == null ? 'Active Threats' : 'Hourly Alerts'}</div>
          <div className="sec-s">{data?.total ?? 0} alerts{hour != null ? ` · observed hour ${hour}` : ''}{tier!=='ALL'?` · filtered: ${tier}`:''}</div>
        </div>
        <div style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}>
          <input className="search" placeholder="Exact anonymized user…"
            value={search} onChange={e=>{setSearch(e.target.value);setPage(1)}} style={{width:220}}/>
          <button className="btn" onClick={exportCSV}>
            <Download size={12}/>Export CSV
          </button>
        </div>
      </div>

      <div className="pills" style={{marginBottom:16}}>
        {TIERS.map(t => (
          <button key={t} className={`pill${tier===t?' active':''}`} onClick={() => {setTier(t);setPage(1)}}>{t}</button>
        ))}
      </div>

      <div style={{display: 'flex', gap: 10, marginBottom: 12}}>
        <select aria-label="Alert status" value={statusFilter} onChange={e => {setStatusFilter(e.target.value);setPage(1)}}><option value="">All statuses</option>{['OPEN','IN_PROGRESS','RESOLVED'].map(s => <option key={s}>{s}</option>)}</select>
        <button className="btn" disabled={page === 1} onClick={() => setPage(p => p-1)}>Previous</button>
        <span>Page {page} · {data?.total ?? 0} alerts</span>
        <button className="btn" disabled={page*50 >= (data?.total || 0)} onClick={() => setPage(p => p+1)}>Next</button>
      </div>
      <div className="card" style={{overflowX:'auto'}}>
        {loading ? <Loading /> : alerts.length===0 ? <Empty text="No alerts match filter" /> : (
          <table className="tbl">
            <thead>
              <tr>
                {sortHeader("alert_id", "ALERT ID")}
                {sortHeader("user_id", "USER")}
                {sortHeader("risk_tier", "TIER")}
                {sortHeader("risk_score", "SCORE")}
                <th>TYPE</th>
                {sortHeader("relative_day", "OBSERVED HOUR")}
                <th>STATUS</th>
                <th>ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map(a => (
                <tr key={a.alert_id} onClick={() => setSel(a)}>
                  <td><span className="mono">{a.alert_id}</span></td>
                  <td>
                    <div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:12,color:'var(--cyan)'}}>{a.user_id}</div>
                    <div style={{fontSize:11,color:'var(--t3)',marginTop:2}}>{a.department}</div>
                  </td>
                  <td><Badge tier={a.risk_tier}/></td>
                  <td>
                    <div style={{display:'flex',alignItems:'center',gap:9}}>
                      <span style={{fontFamily:"'JetBrains Mono',monospace",fontSize:15,fontWeight:700,color:TC[a.risk_tier]}}>
                        {a.risk_score?.toFixed(1)}
                      </span>
                      <div className="rbar">
                        <div className="rbar-f" style={{width:`${a.risk_score||0}%`,background:TC[a.risk_tier]}}/>
                      </div>
                    </div>
                  </td>
                  <td><span style={{fontSize:11,color:'var(--t3)'}}>{a.alert_type?.replace(/_/g,' ')}</span></td>
                  <td><span style={{fontFamily:"'JetBrains Mono',monospace",fontSize:11,color:'var(--t3)'}}>{a.timestamp || `Hour ${a.relative_day}`}</span></td>
                  <td><StatusBadge status={a.status} /></td>
                  <td>
                    <StatusActions alert={a} busyId={busyId} onChange={updateStatus} compact />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
