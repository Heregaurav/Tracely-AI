import { useState } from 'react'
import { useApi, apiFetch } from '../hooks/useApi'
import { Loading, Badge } from '../components/shared'
import { Download, RefreshCw, Server, Database, ShieldCheck } from 'lucide-react'

const MODEL_CFG = [
  ['Dataset',           'CERT Insider Threat r4.2 (CMU)'],
  ['Primary Model',     'Isolation Forest (scikit-learn)'],
  ['Secondary Model',   'Autoencoder / PCA Reconstruction'],
  ['Ensemble Weights',  '60% IF + 40% Autoencoder'],
  ['Features',          '27 behavioral features per user/day'],
  ['Training Mode',     'Unsupervised — no labels required'],
  ['Contamination',     '5% (IsolationForest hyperparameter)'],
  ['Score Range',       '0 – 100 (normalized ensemble)'],
  ['Retraining',        'On-demand via API /api/retrain'],
]

const THRESHOLDS = [
  { tier:'CRITICAL', range:'>95',   desc:'Immediate investigation required' },
  { tier:'HIGH',     range:'85–95', desc:'Escalate to security team' },
  { tier:'MEDIUM',   range:'70–85', desc:'Review within 48 hours' },
  { tier:'LOW',      range:'40–70', desc:'Flag for weekly review' },
  { tier:'NORMAL',   range:'<40',   desc:'Continue monitoring' },
]

export default function Reports() {
  const { data:stats }  = useApi('/api/stats')
  const { data:users }  = useApi('/api/users?limit=500')
  const { data:alerts } = useApi('/api/threats?limit=500')
  const [busy, setBusy] = useState(false)
  const [msg,  setMsg]  = useState('')

  const retrain = async () => {
    setBusy(true); setMsg('')
    try   { const r = await apiFetch('/api/retrain'); setMsg(r.message || 'Retraining started.') }
    catch (e) { setMsg('Error: ' + e.message) }
    finally   { setBusy(false) }
  }

  const exportCSV = (rows, cols, fn) => {
    const csv = [cols.join(','), ...rows.map(r=>cols.map(c=>JSON.stringify(r[c]??'')).join(','))].join('\n')
    const url = URL.createObjectURL(new Blob([csv],{type:'text/csv'}))
    Object.assign(document.createElement('a'),{href:url,download:fn}).click()
  }
  const exportJSON = (data, fn) => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}))
    Object.assign(document.createElement('a'),{href:url,download:fn}).click()
  }

  return (
    <div className="page">
      <div className="sec">
        <div className="sec-t">Reports & System</div>
        <div className="sec-s">Model configuration, live stats, exports and controls</div>
      </div>

      <div className="g2" style={{alignItems:'start'}}>
        {/* Model config */}
        <div className="card">
          <div className="card-h">
            <span className="card-t">Model Configuration</span>
            <Server size={14} color="var(--t3)"/>
          </div>
          <div style={{padding:'4px 0'}}>
            {MODEL_CFG.map(([k,v])=>(
              <div key={k} style={{display:'flex',padding:'9px 18px',borderBottom:'1px solid rgba(255,255,255,.03)'}}>
                <div style={{fontSize:11,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace",width:'44%',flexShrink:0}}>{k}</div>
                <div style={{fontSize:12,color:'var(--t2)'}}>{v}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{display:'flex',flexDirection:'column',gap:14}}>
          {/* Live snapshot */}
          <div className="card">
            <div className="card-h">
              <span className="card-t">Live Snapshot</span>
              <Database size={14} color="var(--t3)"/>
            </div>
            <div className="card-b">
              {!stats ? <Loading/> : (
                <div className="info-grid">
                  {[
                    ['Total Users', stats.total_users,          'var(--blue)'],
                    ['Open Alerts', stats.open_alerts,          'var(--orange)'],
                    ['Critical',    stats.critical_users,       'var(--red)'],
                    ['High Risk',   stats.high_risk_users,      'var(--yellow)'],
                    ['Avg Score',   stats.avg_risk_score?.toFixed(1), 'var(--purple)'],
                    ['Trend',       `${stats.risk_trend_pct>0?'+':''}${stats.risk_trend_pct?.toFixed(1)}%`, stats.risk_trend_pct>0?'var(--red)':'var(--green)'],
                  ].map(([l,v,c])=>(
                    <div key={l} className="info-cell">
                      <div className="info-l">{l}</div>
                      <div style={{fontSize:22,fontFamily:"'JetBrains Mono',monospace",fontWeight:700,color:c,marginTop:4}}>{v}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Retrain */}
          <div className="card">
            <div className="card-h">
              <span className="card-t">Model Controls</span>
              <ShieldCheck size={14} color="var(--t3)"/>
            </div>
            <div className="card-b">
              <p style={{fontSize:12,color:'var(--t3)',marginBottom:14,lineHeight:1.7}}>
                Trigger a full retrain on the latest data. The pipeline runs in a background thread — API stays online.
              </p>
              <button
                onClick={retrain} disabled={busy}
                className="btn btn-primary"
                style={{width:'100%',justifyContent:'center',padding:'10px',opacity:busy?.65:1}}
              >
                <RefreshCw size={13} style={{animation:busy?'rot .7s linear infinite':''}}/>
                {busy ? 'Retraining…' : 'Retrain Models'}
              </button>
              {msg && (
                <div style={{marginTop:10,padding:'9px 12px',borderRadius:7,background:'var(--bg3)',fontSize:11,color:'var(--t2)',fontFamily:"'JetBrains Mono',monospace"}}>
                  {msg}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Thresholds */}
      <div className="card gap16">
        <div className="card-h"><span className="card-t">Risk Tier Thresholds</span></div>
        <table className="tbl">
          <thead><tr><th>TIER</th><th>SCORE RANGE</th><th>REQUIRED ACTION</th></tr></thead>
          <tbody>
            {THRESHOLDS.map(t=>(
              <tr key={t.tier} style={{cursor:'default'}}>
                <td><Badge tier={t.tier}/></td>
                <td><span className="mono">{t.range}</span></td>
                <td style={{fontSize:12,color:'var(--t2)'}}>{t.desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Exports */}
      <div className="card">
        <div className="card-h"><span className="card-t">Export Data</span></div>
        <div className="card-b">
          <div style={{display:'flex',flexWrap:'wrap',gap:10}}>
            <button className="btn" onClick={()=>exportCSV(users?.users||[],['user','name','department','risk_tier','max_risk_score','avg_risk_score','trend'],'user_risk_scores.csv')}>
              <Download size={12}/>User Risk Scores (CSV)
            </button>
            <button className="btn" onClick={()=>exportCSV(alerts?.alerts||[],['alert_id','user_id','department','risk_tier','risk_score','alert_type','status','timestamp'],'tracely_ai_alerts.csv')}>
              <Download size={12}/>Alerts (CSV)
            </button>
            <button className="btn" onClick={()=>exportJSON({stats,generated:new Date().toISOString()},'tracely_ai_report.json')}>
              <Download size={12}/>Full Report (JSON)
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
