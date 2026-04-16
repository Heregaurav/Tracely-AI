import { useState, useMemo } from 'react'
import { useApi, apiFetch } from '../hooks/useApi'
import { Badge, Loading, Empty, ScoreDonut } from '../components/shared'
import { CheckCircle2, Download, LoaderCircle, PlayCircle, Siren, X } from 'lucide-react'

const TC = { CRITICAL:'var(--red)', HIGH:'var(--orange)', MEDIUM:'var(--yellow)', LOW:'var(--cyan)', NORMAL:'var(--green)' }
const TIERS = ['ALL','CRITICAL','HIGH','MEDIUM','LOW','NORMAL']
const STATUS_META = {
  OPEN: { label: 'Resolve', accent: 'var(--orange)', bg: 'rgba(251,146,60,.15)' },
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
    { key: 'OPEN', label: 'Resolve', Icon: Siren },
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

function AlertModal({ alert, onClose, busyId, onStatusChange }) {
  if (!alert) return null
  return (
    <div className="overlay" onClick={e => e.target===e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-h">
          <div style={{display:'flex',alignItems:'center',gap:16}}>
            <ScoreDonut score={alert.risk_score||0} size={62}/>
            <div>
              <div className="modal-title">{alert.alert_id}</div>
              <div style={{fontSize:12,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace",marginTop:3}}>
                {alert.user_id} · {alert.department}
              </div>
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
              ['Alert ID',   alert.alert_id],
              ['User',       alert.user_id],
              ['Department', alert.department],
              ['Risk Score', alert.risk_score?.toFixed(2)],
              ['IF Score',   alert.if_score!=null ? alert.if_score.toFixed(2) : '—'],
              ['AE Score',   alert.ae_score!=null ? alert.ae_score.toFixed(2)  : '—'],
              ['Alert Type', alert.alert_type?.replace(/_/g,' ')],
              ['Status',     alert.status],
              ['Date',       alert.timestamp?.slice(0,10)],
              ['Time',       alert.timestamp?.slice(11,19)||'—'],
            ].map(([k,v]) => (
              <div key={k} className="info-cell">
                <div className="info-l">{k}</div>
                <div className="info-v" style={{fontFamily:['Risk Score','IF Score','AE Score','Alert ID'].includes(k)?'"JetBrains Mono",monospace':'inherit'}}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 18 }}>
            <div className="info-l" style={{ marginBottom: 10 }}>Threat Workflow</div>
            <StatusActions alert={alert} busyId={busyId} onChange={onStatusChange} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Threats() {
  const [tier,  setTier]  = useState('ALL')
  const [search,setSearch]= useState('')
  const [sel,   setSel]   = useState(null)
  const [sc,    setSC]    = useState('risk_score')
  const [asc,   setAsc]   = useState(false)
  const [busyId,setBusyId]= useState(null)

  const { data, loading, refetch } = useApi(
    tier==='ALL' ? '/api/threats?limit=500' : `/api/threats?tier=${tier}&limit=500`,
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
  const SH = ({col,label}) => (
    <th onClick={() => sort(col)}>
      {label}{sc===col?(asc?' ↑':' ↓'):''}
    </th>
  )

  const exportCSV = () => {
    const cols = ['alert_id','user_id','department','risk_tier','risk_score','alert_type','status','timestamp']
    const csv  = [cols.join(','), ...alerts.map(a=>cols.map(c=>JSON.stringify(a[c]??'')).join(','))].join('\n')
    const url  = URL.createObjectURL(new Blob([csv],{type:'text/csv'}))
    Object.assign(document.createElement('a'),{href:url,download:'tracely_ai_alerts.csv'}).click()
  }

  const updateStatus = async (alertId, status) => {
    setBusyId(alertId)
    try {
      const response = await apiFetch(`/api/threats/${alertId}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      if (sel?.alert_id === alertId) setSel(response.alert)
      refetch()
    } catch (err) {
      console.error(err)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="page">
      {sel && <AlertModal alert={sel} onClose={() => setSel(null)} busyId={busyId} onStatusChange={updateStatus} />}

      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:20,flexWrap:'wrap',gap:12}}>
        <div className="sec">
          <div className="sec-t">Active Threats</div>
          <div className="sec-s">{alerts.length} alerts{tier!=='ALL'?` · filtered: ${tier}`:''}</div>
        </div>
        <div style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}>
          <input className="search" placeholder="Search user / dept / ID…"
            value={search} onChange={e=>setSearch(e.target.value)} style={{width:220}}/>
          <button className="btn" onClick={exportCSV}>
            <Download size={12}/>Export CSV
          </button>
        </div>
      </div>

      <div className="pills" style={{marginBottom:16}}>
        {TIERS.map(t => (
          <button key={t} className={`pill${tier===t?' active':''}`} onClick={() => setTier(t)}>{t}</button>
        ))}
      </div>

      <div className="card" style={{overflowX:'auto'}}>
        {loading ? <Loading /> : alerts.length===0 ? <Empty text="No alerts match filter" /> : (
          <table className="tbl">
            <thead>
              <tr>
                <SH col="alert_id"   label="ALERT ID"/>
                <SH col="user_id"    label="USER"/>
                <SH col="risk_tier"  label="TIER"/>
                <SH col="risk_score" label="SCORE"/>
                <th>TYPE</th>
                <SH col="timestamp"  label="DATE"/>
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
                  <td><span style={{fontFamily:"'JetBrains Mono',monospace",fontSize:11,color:'var(--t3)'}}>{a.timestamp?.slice(0,10)}</span></td>
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
