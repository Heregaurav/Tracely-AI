import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { Badge, Loading, Empty, Avatar, TrendBadge } from '../components/shared'
import UserModal from './UserModal'
import { LayoutGrid, List, Eye, ShieldAlert, Waves } from 'lucide-react'

const TC = { CRITICAL:'var(--red)', HIGH:'var(--orange)', MEDIUM:'var(--yellow)', LOW:'var(--cyan)', NORMAL:'var(--green)' }
const TIERS = ['ALL','CRITICAL','HIGH','MEDIUM','LOW','NORMAL']

function UCard({ u, onClick }) {
  const tier = u.risk_tier || 'NORMAL'
  const name = u.name || u.user || '?'
  return (
    <div className={`ucard ${tier}`} onClick={() => onClick(u.user)}>
      <div style={{display:'flex',alignItems:'flex-start',justifyContent:'space-between',marginBottom:14}}>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <Avatar name={name} tier={tier} size={38}/>
          <div>
            <div style={{fontSize:13,fontWeight:600,color:'var(--t1)'}}>{name}</div>
            <div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:10,color:'var(--t3)',marginTop:2}}>{u.user}</div>
          </div>
        </div>
        <Badge tier={tier}/>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8,marginBottom:14}}>
        {[['DEPT',u.department||'—'],['ROLE',u.role||'—'],['MAX',u.max_risk_score?.toFixed(1)||'—'],['H-DAYS',u.high_risk_days||0]].map(([l,v])=>(
          <div key={l} style={{background:'var(--bg3)',borderRadius:6,padding:'7px 10px'}}>
            <div style={{fontSize:9,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace",letterSpacing:'.1em',marginBottom:3}}>{l}</div>
            <div style={{fontSize:12,fontWeight:l==='MAX'?700:400,color:l==='MAX'?TC[tier]:'var(--t2)',fontFamily:l==='MAX'?"'JetBrains Mono',monospace":'inherit'}}>{v}</div>
          </div>
        ))}
      </div>

      <div>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:5}}>
          <span style={{fontSize:10,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace",letterSpacing:'.08em'}}>RISK SCORE</span>
          <div style={{display:'flex',alignItems:'center',gap:6}}>
            <TrendBadge dir={u.trend}/>
            <span style={{fontFamily:"'JetBrains Mono',monospace",fontSize:13,fontWeight:700,color:TC[tier]}}>{u.max_risk_score?.toFixed(1)}</span>
          </div>
        </div>
        <div style={{height:4,background:'rgba(255,255,255,.07)',borderRadius:2,overflow:'hidden'}}>
          <div style={{height:'100%',width:`${Math.min(100,u.max_risk_score||0)}%`,background:TC[tier],borderRadius:2,transition:'width .5s'}}/>
        </div>
      </div>

      <div style={{display:'flex',gap:6,flexWrap:'wrap',marginTop:12}}>
        <span className="micro-chip"><Eye size={11}/> avg {u.avg_risk_score?.toFixed(1) || '0.0'}</span>
        <span className="micro-chip"><ShieldAlert size={11}/> {u.high_risk_days || 0} high-risk days</span>
        <span className="micro-chip"><Waves size={11}/> trend {u.trend || 'stable'}</span>
      </div>
    </div>
  )
}

export default function Users() {
  const [tier,  setTier]  = useState('ALL')
  const [search,setSearch]= useState('')
  const [view,  setView]  = useState('grid')
  const [sc,    setSC]    = useState('max_risk_score')
  const [asc,   setAsc]   = useState(false)
  const [sel,   setSel]   = useState(null)

  const { data, loading } = useApi(
    tier==='ALL'
      ? `/api/users?sort=${sc}&order=${asc?'asc':'desc'}&limit=500`
      : `/api/users?tier=${tier}&sort=${sc}&order=${asc?'asc':'desc'}&limit=500`,
    [tier, sc, asc]
  )

  const users = useMemo(() => {
    let list = data?.users || []
    if (search) {
      const q = search.toLowerCase()
      list = list.filter(u =>
        u.user?.toLowerCase().includes(q) ||
        u.name?.toLowerCase().includes(q) ||
        u.department?.toLowerCase().includes(q)
      )
    }
    return list
  }, [data, search])

  const sort = col => { if(col===sc) setAsc(a=>!a); else {setSC(col);setAsc(false)} }
  const SH = ({col,lbl}) => (
    <th onClick={()=>sort(col)} style={{cursor:'pointer',userSelect:'none'}}>
      {lbl}{sc===col?(asc?' ↑':' ↓'):''}
    </th>
  )

  const summary = useMemo(() => {
    const total = users.length
    const critical = users.filter(u => u.risk_tier === 'CRITICAL').length
    const high = users.filter(u => u.risk_tier === 'HIGH').length
    const avg = total ? users.reduce((sum, u) => sum + (u.avg_risk_score || 0), 0) / total : 0
    return { total, critical, high, avg }
  }, [users])

  return (
    <div className="page">
      {sel && <UserModal userId={sel} onClose={() => setSel(null)}/>}

      <div className="hero" style={{ marginBottom: 20 }}>
        <div>
          <div className="hero-kicker">User Watchlist</div>
          <h1 className="hero-title">Clearer user risk monitoring with faster drill-downs</h1>
          <p className="hero-copy">
            Search, sort, and open individual dossiers to inspect behavior signals like files accessed, USB activity, external emails, sensitive file access, and session duration.
          </p>
        </div>
        <div className="hero-chip">{summary.total} users in current view</div>
      </div>

      <div className="feature-grid" style={{ marginBottom: 18 }}>
        {[
          ['Visible Users', summary.total, 'var(--blue)', 'Users in the current filtered list'],
          ['Critical', summary.critical, 'var(--red)', 'Immediate investigation priority'],
          ['High Risk', summary.high, 'var(--orange)', 'Escalated watchlist subjects'],
          ['Avg Score', summary.avg.toFixed(1), 'var(--cyan)', 'Mean score across the filtered list'],
        ].map(([label, value, color, sub]) => (
          <div key={label} className="feature-panel">
            <div className="feature-label">{label}</div>
            <div className="feature-value" style={{ color }}>{value}</div>
            <div className="feature-sub">{sub}</div>
          </div>
        ))}
      </div>

      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:20,flexWrap:'wrap',gap:12}}>
        <div className="sec" style={{marginBottom:0}}>
          <div className="sec-t">User Watchlist</div>
          <div className="sec-s">{users.length} subjects{tier!=='ALL'?` · ${tier}`:''}</div>
        </div>
        <div style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}>
          <input className="search" placeholder="Search name / ID / dept…"
            value={search} onChange={e=>setSearch(e.target.value)} style={{width:220}}/>
          <div className="tab-row">
            <button className={`tab${view==='grid'?' active':''}`} onClick={()=>setView('grid')}><LayoutGrid size={13}/></button>
            <button className={`tab${view==='list'?' active':''}`} onClick={()=>setView('list')}><List size={13}/></button>
          </div>
        </div>
      </div>

      <div className="pills" style={{marginBottom:16}}>
        {TIERS.map(t=>(
          <button key={t} className={`pill${tier===t?' active':''}`} onClick={()=>setTier(t)}>{t}</button>
        ))}
      </div>

      {loading ? <Loading text="Building watchlist…"/> : users.length===0 ? <Empty text="No subjects found"/> :
        view==='grid' ? (
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(268px,1fr))',gap:14}}>
            {users.map(u=><UCard key={u.user} u={u} onClick={setSel}/>)}
          </div>
        ) : (
          <div className="card" style={{overflowX:'auto'}}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>USER</th>
                  <SH col="max_risk_score" lbl="MAX"/>
                  <SH col="avg_risk_score" lbl="AVG"/>
                  <SH col="risk_tier"      lbl="TIER"/>
                  <SH col="department"     lbl="DEPT"/>
                  <SH col="high_risk_days" lbl="HIGH DAYS"/>
                  <th>TREND</th>
                </tr>
              </thead>
              <tbody>
                {users.map(u=>(
                  <tr key={u.user} onClick={()=>setSel(u.user)}>
                    <td>
                      <div style={{display:'flex',alignItems:'center',gap:10}}>
                        <Avatar name={u.name||u.user} tier={u.risk_tier} size={30}/>
                        <div>
                          <div style={{fontSize:13,color:'var(--t1)',fontWeight:500}}>{u.name||u.user}</div>
                          <div className="mono" style={{marginTop:1}}>{u.user}</div>
                        </div>
                      </div>
                    </td>
                    <td><span style={{fontFamily:"'JetBrains Mono',monospace",fontSize:15,fontWeight:700,color:TC[u.risk_tier]}}>{u.max_risk_score?.toFixed(1)}</span></td>
                    <td><span style={{fontFamily:"'JetBrains Mono',monospace",fontSize:12,color:'var(--t2)'}}>{u.avg_risk_score?.toFixed(1)}</span></td>
                    <td><Badge tier={u.risk_tier}/></td>
                    <td style={{fontSize:12,color:'var(--t2)'}}>{u.department||'—'}</td>
                    <td><span className="mono">{u.high_risk_days}d</span></td>
                    <td><TrendBadge dir={u.trend}/></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    </div>
  )
}
