import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { Loading, Empty } from '../components/shared'

const DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
const DS   = ['MON','TUE','WED','THU','FRI','SAT','SUN']

const cellBg = s => {
  if (!s||s<3)  return 'rgba(91,141,246,.08)'
  if (s < 15)   return 'rgba(34,211,238,.18)'
  if (s < 30)   return 'rgba(251,191,36,.26)'
  if (s < 50)   return 'rgba(251,146,60,.36)'
  if (s < 70)   return 'rgba(248,113,113,.50)'
  return               'rgba(248,113,113,.82)'
}
const cellFg = s => s > 30 ? 'rgba(255,255,255,.88)' : 'rgba(255,255,255,.4)'

export default function Heatmap() {
  const { data, loading } = useApi('/api/heatmap')
  const [tip, setTip] = useState(null)

  const { depts, matrix } = useMemo(() => {
    if (!data?.heatmap?.length) return { depts:[], matrix:{} }
    const depts = [...new Set(data.heatmap.map(d => d.department))].sort()
    const matrix = {}
    data.heatmap.forEach(d => {
      if (!matrix[d.department]) matrix[d.department] = {}
      matrix[d.department][d.dow] = d.avg_risk
    })
    return { depts, matrix }
  }, [data])

  if (loading) return <div className="page"><Loading text="Building heatmap…"/></div>

  return (
    <div className="page">
      <div className="sec">
        <div className="sec-t">Risk Heatmap</div>
        <div className="sec-s">Average anomaly score · Department × Day of week · Darker = higher risk</div>
      </div>

      {!depts.length ? <Empty text="Insufficient data" /> : (
        <>
          {/* Legend */}
          <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:20}}>
            <span style={{fontSize:11,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace"}}>RISK LEVEL:</span>
            {[[0,'Low'],[20,'Moderate'],[40,'High'],[65,'Critical']].map(([v,l])=>(
              <div key={v} style={{display:'flex',alignItems:'center',gap:5}}>
                <div style={{width:28,height:14,borderRadius:4,background:cellBg(v),border:'1px solid rgba(255,255,255,.06)'}}/>
                <span style={{fontSize:10,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace"}}>{l}</span>
              </div>
            ))}
          </div>

          <div className="card" style={{padding:0,overflowX:'auto'}}>
            <div style={{padding:'18px 22px',minWidth:540}}>
              {/* Day column headers */}
              <div style={{display:'grid',gridTemplateColumns:'120px repeat(7,1fr)',gap:3,marginBottom:5}}>
                <div/>
                {DS.map((d,i)=>(
                  <div key={i} style={{
                    textAlign:'center',fontFamily:"'JetBrains Mono',monospace",fontSize:10,
                    color:i>=5?'var(--t4)':'var(--t3)',letterSpacing:'.08em',padding:'3px 0'
                  }}>{d}</div>
                ))}
              </div>

              {depts.map(dept => (
                <div key={dept} style={{display:'grid',gridTemplateColumns:'120px repeat(7,1fr)',gap:3,marginBottom:3}}>
                  <div style={{display:'flex',alignItems:'center',paddingRight:10}}>
                    <span style={{fontSize:11,color:'var(--t2)',fontFamily:"'JetBrains Mono',monospace",whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{dept}</span>
                  </div>
                  {DAYS.map((day,i) => {
                    const s = matrix[dept]?.[day] || 0
                    return (
                      <div key={day} className="hmc"
                        style={{background:cellBg(s),color:cellFg(s)}}
                        onMouseEnter={e => setTip({dept,day,s:s.toFixed(1),x:e.clientX,y:e.clientY})}
                        onMouseLeave={() => setTip(null)}
                        onMouseOver={e => e.currentTarget.style.transform='scale(1.1)'}
                        onMouseOut={e => e.currentTarget.style.transform=''}
                      >
                        {s > 1 ? s.toFixed(0) : ''}
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>
          </div>

          {/* Floating tooltip */}
          {tip && (
            <div style={{
              position:'fixed',left:tip.x+14,top:tip.y-14,pointerEvents:'none',zIndex:999,
              background:'var(--bg1)',border:'1px solid var(--line2)',borderRadius:8,
              padding:'9px 13px',fontFamily:"'JetBrains Mono',monospace",fontSize:11,
              boxShadow:'0 8px 24px rgba(0,0,0,.5)'
            }}>
              <div style={{color:'var(--t3)',marginBottom:4}}>{tip.dept} · {tip.day}</div>
              <div style={{fontSize:18,fontWeight:700,color:'var(--t1)'}}>{tip.s}</div>
              <div style={{color:'var(--t3)',fontSize:10,marginTop:2}}>avg risk score</div>
            </div>
          )}

          {/* Top combos */}
          <div style={{marginTop:22}}>
            <div style={{fontSize:11,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace",letterSpacing:'.1em',textTransform:'uppercase',marginBottom:14}}>Top Risk Combinations</div>
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(190px,1fr))',gap:10}}>
              {(data?.heatmap||[]).filter(d=>d.avg_risk>0).sort((a,b)=>b.avg_risk-a.avg_risk).slice(0,6).map((d,i)=>{
                const c = d.avg_risk>60?'var(--red)':d.avg_risk>40?'var(--orange)':d.avg_risk>20?'var(--yellow)':'var(--cyan)'
                return (
                  <div key={i} style={{background:'var(--bg2)',border:'1px solid var(--line)',borderRadius:8,padding:'14px 16px',borderLeft:`3px solid ${c}`}}>
                    <div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:11,color:'var(--t2)',marginBottom:6}}>{d.department} · {d.dow?.slice(0,3).toUpperCase()}</div>
                    <div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:24,fontWeight:700,color:c}}>{d.avg_risk.toFixed(1)}</div>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
