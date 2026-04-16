import { useEffect, useState } from 'react'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { apiFetch } from '../hooks/useApi'
import { Badge, Loading, Avatar, TrendBadge, ChartTooltip } from '../components/shared'
import { X } from 'lucide-react'

const TC = { CRITICAL:'var(--red)', HIGH:'var(--orange)', MEDIUM:'var(--yellow)', LOW:'var(--cyan)', NORMAL:'var(--green)' }
const BKEYS = ['files_accessed','usb_count','emails_external','after_hours_logins','sensitive_files','email_attachments','session_duration_total','unique_pcs']
const BLABELS = { files_accessed:'Files Accessed', usb_count:'USB Usage', emails_external:'External Emails', after_hours_logins:'After-Hours Logins', sensitive_files:'Sensitive Files', email_attachments:'Email Attachments', session_duration_total:'Session Duration', unique_pcs:'Unique PCs' }
const BMAXES = { files_accessed:80, usb_count:10, emails_external:20, after_hours_logins:5, sensitive_files:8, email_attachments:15, session_duration_total:600, unique_pcs:5 }

function barColor(pct) {
  return pct>75?'var(--red)':pct>50?'var(--orange)':pct>25?'var(--yellow)':'var(--cyan)'
}

export default function UserModal({ userId, onClose }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!userId) return
    setLoading(true)
    apiFetch(`/api/users/${userId}`)
      .then(d => setData(d))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [userId])

  if (!userId) return null

  const chartData = (data?.daily_scores || []).map(d => ({
    date:  (d.day || '').slice(5,10),
    score: +(d.risk_score || 0).toFixed(1),
  }))

  // Behavior averages from last 30 days
  const recent = (data?.daily_scores || []).slice(-30)
  const bavg = {}
  BKEYS.forEach(k => {
    const vals = recent.map(d => d[k] || 0)
    bavg[k] = vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : 0
  })

  const name  = data?.ldap?.name || data?.name || userId
  const tier  = data?.risk_tier || 'NORMAL'
  const dept  = data?.ldap?.department || data?.department || '—'
  const role  = data?.ldap?.role || '—'
  const email = data?.ldap?.email || '—'
  const peak  = Math.max(...(data?.daily_scores||[]).map(d=>d.risk_score||0), 0)
  const avg   = data?.avg_risk_score || 0
  const latest = recent[recent.length - 1] || {}

  return (
    <div className="overlay" onClick={e => e.target===e.currentTarget && onClose()}>
      <div className="modal" style={{width:'min(980px,96vw)'}}>
        {/* Header */}
        <div className="modal-h">
          <div style={{display:'flex',alignItems:'center',gap:16}}>
            <Avatar name={name} tier={tier} size={46}/>
            <div>
              <div className="modal-title">{name}</div>
              <div style={{fontSize:11,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace",marginTop:3}}>
                {userId} · {dept} · {role}
              </div>
              <div style={{marginTop:7,display:'flex',alignItems:'center',gap:8}}>
                <Badge tier={tier}/>
                <TrendBadge dir={data?.trend}/>
              </div>
            </div>
          </div>
          <button className="modal-x" onClick={onClose}><X size={16}/></button>
        </div>

        <div className="modal-b">
          {loading ? <Loading text="Loading dossier…" /> : (
            <>
              <div className="hero inset" style={{ marginBottom: 22 }}>
                <div>
                  <div className="hero-kicker">User Behavior Dossier</div>
                  <div className="hero-title" style={{ fontSize: 26 }}>Behavior, anomalies, and alert context in one place</div>
                  <div className="hero-copy">
                    Latest day tracked: {(latest.day || '').slice(0, 10) || 'No recent activity'} · Email: {email}
                  </div>
                </div>
              </div>

              <div className="feature-grid" style={{marginBottom:22}}>
                {[
                  ['Peak Score', peak.toFixed(1), TC[tier]||TC.NORMAL, 'Highest risk score on record'],
                  ['Average Score', avg.toFixed(1), 'var(--blue)', '30-day user risk average'],
                  ['Open Alerts', data?.alerts?.length||0, (data?.alerts?.length||0)>0?'var(--orange)':'var(--green)', 'Triggered alert events in the dossier'],
                  ['Active Days', data?.total_days_active||0, 'var(--cyan)', 'Tracked behavior days for this user'],
                ].map(([l,v,c,s]) => (
                  <div key={l} className="feature-panel">
                    <div className="feature-label">{l}</div>
                    <div className="feature-value" style={{color:c}}>{v}</div>
                    <div className="feature-sub">{s}</div>
                  </div>
                ))}
              </div>

              <div style={{display:'grid',gridTemplateColumns:'1.3fr .9fr',gap:18}}>
                <div>
                  <div className="card" style={{ marginBottom: 18 }}>
                    <div className="card-h"><span className="card-t">Risk Score History</span></div>
                    <div className="card-b">
                      {!chartData.length ? (
                        <div style={{textAlign:'center',color:'var(--t3)',padding:20,fontFamily:"'JetBrains Mono',monospace",fontSize:12}}>No history available</div>
                      ) : (
                        <ResponsiveContainer width="100%" height={180}>
                          <AreaChart data={chartData} margin={{top:4,right:8,left:-24,bottom:0}}>
                            <defs>
                              <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%"  stopColor="#5b8df6" stopOpacity={0.25}/>
                                <stop offset="95%" stopColor="#5b8df6" stopOpacity={0}/>
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3"/>
                            <XAxis dataKey="date" tick={{fill:'var(--t3)',fontSize:9,fontFamily:"'JetBrains Mono',monospace"}} tickLine={false} axisLine={false} interval="preserveStartEnd"/>
                            <YAxis domain={[0,100]} tick={{fill:'var(--t3)',fontSize:9,fontFamily:"'JetBrains Mono',monospace"}} tickLine={false} axisLine={false}/>
                            <Tooltip content={<ChartTooltip/>}/>
                            <ReferenceLine y={85} stroke="var(--red)" strokeDasharray="4 3" strokeWidth={0.8}/>
                            <ReferenceLine y={70} stroke="var(--orange)" strokeDasharray="4 3" strokeWidth={0.8}/>
                            <Area type="monotone" dataKey="score" name="Risk Score" stroke="#5b8df6" strokeWidth={2} fill="url(#sg)" dot={false}/>
                          </AreaChart>
                        </ResponsiveContainer>
                      )}
                    </div>
                  </div>

                  <div style={{fontSize:11,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace",letterSpacing:'.08em',marginBottom:12,textTransform:'uppercase'}}>Behavior Snapshot (30-day avg)</div>
                  <div className="metric-spotlight-grid" style={{ marginBottom: 16 }}>
                    {BKEYS.map(k => (
                      <div key={k} className="metric-spotlight">
                        <div className="metric-spotlight-label">{BLABELS[k]}</div>
                        <div className="metric-spotlight-value">{(bavg[k]||0).toFixed(1)}</div>
                      </div>
                    ))}
                  </div>

                  {BKEYS.map(k => {
                    const pct = Math.min(100, ((bavg[k]||0) / BMAXES[k]) * 100)
                    return (
                      <div key={k} className="mbar">
                        <div className="mbar-l">{BLABELS[k]}</div>
                        <div className="mbar-t">
                          <div className="mbar-f" style={{width:`${pct}%`,background:barColor(pct)}}/>
                        </div>
                        <div className="mbar-v">{(bavg[k]||0).toFixed(1)}</div>
                      </div>
                    )
                  })}
                </div>

                <div>
                  <div className="card" style={{ marginBottom: 16 }}>
                    <div className="card-h"><span className="card-t">Alert History</span></div>
                    <div className="card-b">
                      {!data?.alerts?.length ? (
                        <div style={{color:'var(--t3)',fontSize:12,fontFamily:"'JetBrains Mono',monospace",paddingTop:4}}>No alerts on record</div>
                      ) : data.alerts.slice(0,7).map(a => (
                        <div key={a.alert_id} className="signal-card" style={{ marginBottom: 10 }}>
                          <div className="signal-top">
                            <Badge tier={a.risk_tier}/>
                            <div className="signal-badge" style={{ color: TC[a.risk_tier], borderColor: `${TC[a.risk_tier]}55` }}>
                              {a.risk_score?.toFixed(1)}
                            </div>
                          </div>
                          <div className="signal-title" style={{ marginTop: 8 }}>
                            {a.alert_type?.replace(/_/g,' ')}
                          </div>
                          <div className="signal-caption">{a.timestamp?.slice(0,10)} · {a.message || 'Flagged user activity'}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {data?.ldap && (
                    <div className="card">
                      <div className="card-h"><span className="card-t">Profile</span></div>
                      <div className="card-b">
                        {[['Email',email],['Team',data.ldap.team||'—'],['PC',data.ldap.pc||'—']].map(([l,v])=>(
                          <div key={l} style={{display:'flex',justifyContent:'space-between',padding:'8px 0',borderBottom:'1px solid rgba(255,255,255,.04)'}}>
                            <span style={{fontSize:11,color:'var(--t3)'}}>{l}</span>
                            <span style={{fontSize:11,color:'var(--t2)',fontFamily:"'JetBrains Mono',monospace",textAlign:'right'}}>{v}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
