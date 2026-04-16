import { useApi, usePolling } from '../hooks/useApi'
import { Badge, Loading, Empty, ChartTooltip } from '../components/shared'
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

const TC = { CRITICAL:'var(--red)', HIGH:'var(--orange)', MEDIUM:'var(--yellow)', LOW:'var(--cyan)', NORMAL:'var(--green)' }
const TIERS = ['CRITICAL','HIGH','MEDIUM','LOW','NORMAL']
const rc = v => v>=70?'var(--red)':v>=50?'var(--orange)':v>=30?'var(--yellow)':'var(--cyan)'

export default function Overview({ onNavigate }) {
  const { data:stats }   = usePolling('/api/stats', 30000)
  const { data:threats } = usePolling('/api/threats?limit=10', 30000)
  const { data:tl }      = useApi('/api/timeline?days=60')
  const { data:depts }   = useApi('/api/departments')

  const chartData = (tl?.timeline||[]).map(d => ({ date:(d.day||'').slice(5), avg:+(d.risk_score_avg||0).toFixed(1), max:+(d.risk_score_max||0).toFixed(1) }))
  const deptData  = (depts?.departments||[]).sort((a,b)=>b.avg_risk-a.avg_risk).slice(0,8).map(d=>({name:d.department,v:+d.avg_risk.toFixed(1)}))
  const tierDist  = stats?.tier_distribution || {}
  const trendPct  = stats?.risk_trend_pct || 0

  const cards = [
    {label:'TOTAL USERS',   val:stats?.total_users,              color:'c-blue',   sub:'monitored'},
    {label:'OPEN ALERTS',   val:stats?.open_alerts,              color:'c-orange',  sub:'require review'},
    {label:'HIGH RISK',      val:stats?.high_risk_users,          color:'c-red',    sub:'users flagged'},
    {label:'CRITICAL',       val:stats?.critical_users,           color:'c-red',    sub:'immediate action'},
    {label:'AVG RISK SCORE', val:stats?.avg_risk_score?.toFixed(1),color:'c-purple',sub:`${Math.abs(trendPct).toFixed(1)}% vs last week`,trend:trendPct>0?'up':trendPct<0?'down':'stable'},
  ]

  return (
    <div className="page">
      <div className="stats-row">
        {cards.map(({label,val,color,sub,trend})=>(
          <div key={label} className={`scard ${color}`}>
            <div className="s-lbl">{label}</div>
            <div className={`s-val ${color}`}>{val??'—'}</div>
            <div className="s-sub">
              {trend==='up' && <TrendingUp size={11} color="var(--red)"/>}
              {trend==='down' && <TrendingDown size={11} color="var(--green)"/>}
              {trend==='stable' && <Minus size={11} color="var(--t3)"/>}
              {sub}
            </div>
          </div>
        ))}
      </div>

      <div className="g31">
        <div className="card">
          <div className="card-h">
            <span className="card-t">Risk Timeline — 60 Days</span>
            <div style={{display:'flex',gap:12,fontSize:11,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace"}}>
              <span style={{color:'var(--blue)'}}>— Avg</span>
              <span style={{color:'var(--orange)'}}>╌ Max</span>
            </div>
          </div>
          <div style={{padding:'14px 8px 8px'}}>
            {!chartData.length?<Empty text="No data"/>:(
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={chartData} margin={{top:4,right:8,left:-24,bottom:0}}>
                  <defs>
                    <linearGradient id="ga" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#5b8df6" stopOpacity={0.25}/>
                      <stop offset="95%" stopColor="#5b8df6" stopOpacity={0}/>
                    </linearGradient>
                    <linearGradient id="gb" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#fb923c" stopOpacity={0.15}/>
                      <stop offset="95%" stopColor="#fb923c" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3"/>
                  <XAxis dataKey="date" tick={{fill:'var(--t3)',fontSize:10,fontFamily:"'JetBrains Mono',monospace"}} tickLine={false} axisLine={false} interval="preserveStartEnd"/>
                  <YAxis domain={[0,100]} tick={{fill:'var(--t3)',fontSize:10,fontFamily:"'JetBrains Mono',monospace"}} tickLine={false} axisLine={false}/>
                  <Tooltip content={<ChartTooltip/>}/>
                  <Area type="monotone" dataKey="max" name="Max Risk" stroke="#fb923c" strokeWidth={1.5} strokeDasharray="5 3" fill="url(#gb)"/>
                  <Area type="monotone" dataKey="avg" name="Avg Risk" stroke="#5b8df6" strokeWidth={2} fill="url(#ga)"/>
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-h">
            <span className="card-t">Live Alerts</span>
            <button className="btn btn-sm" onClick={()=>onNavigate('threats')}>View all →</button>
          </div>
          <div style={{maxHeight:270,overflowY:'auto'}}>
            {!threats?.alerts?.length?<Empty text="No active alerts"/>:
              threats.alerts.map(a=>(
                <div key={a.alert_id} className="alert-item">
                  <div className="a-dot" style={{background:TC[a.risk_tier]||'#666'}}/>
                  <div style={{flex:1,minWidth:0}}>
                    <div className="a-msg">
                      <span className="mono">{a.user_id}</span>
                      <span style={{color:'var(--t3)',margin:'0 6px'}}>·</span>
                      <span style={{fontSize:12,color:'var(--t2)'}}>{a.alert_type?.replace(/_/g,' ')}</span>
                    </div>
                    <div className="a-meta">
                      <Badge tier={a.risk_tier}/>
                      <span style={{color:TC[a.risk_tier]}}>{a.risk_score?.toFixed(1)}</span>
                      <span>{a.department}</span>
                    </div>
                  </div>
                </div>
              ))
            }
          </div>
        </div>
      </div>

      <div className="g2">
        <div className="card">
          <div className="card-h"><span className="card-t">Risk by Department</span></div>
          <div style={{padding:'12px 8px 8px'}}>
            {!deptData.length?<Empty/>:(
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={deptData} layout="vertical" margin={{top:0,right:36,left:10,bottom:0}}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false}/>
                  <XAxis type="number" domain={[0,100]} tick={{fill:'var(--t3)',fontSize:10,fontFamily:"'JetBrains Mono',monospace"}} tickLine={false} axisLine={false}/>
                  <YAxis type="category" dataKey="name" width={82} tick={{fill:'var(--t2)',fontSize:11,fontFamily:"'JetBrains Mono',monospace"}} tickLine={false} axisLine={false}/>
                  <Tooltip content={<ChartTooltip/>}/>
                  <Bar dataKey="v" name="Avg Risk" radius={[0,4,4,0]} barSize={13}>
                    {deptData.map((d,i)=><Cell key={i} fill={rc(d.v)}/>)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-h"><span className="card-t">Risk Distribution</span></div>
          <div className="card-b">
            {TIERS.map(tier=>{
              const count=tierDist[tier]||0
              const pct=Math.round((count/(stats?.total_users||1))*100)
              return(
                <div key={tier} style={{marginBottom:15}}>
                  <div style={{display:'flex',justifyContent:'space-between',marginBottom:5}}>
                    <Badge tier={tier}/>
                    <span style={{fontFamily:"'JetBrains Mono',monospace",fontSize:11,color:'var(--t3)'}}>
                      {count} <span style={{opacity:.6}}>({pct}%)</span>
                    </span>
                  </div>
                  <div style={{height:5,background:'rgba(255,255,255,.06)',borderRadius:3,overflow:'hidden'}}>
                    <div style={{height:'100%',width:`${pct}%`,background:TC[tier],borderRadius:3,transition:'width .6s'}}/>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
