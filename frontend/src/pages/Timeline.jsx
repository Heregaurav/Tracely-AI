import { useState, useMemo } from 'react'
import { ComposedChart, Area, Line, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { useApi } from '../hooks/useApi'
import { Loading, Empty, ChartTooltip } from '../components/shared'

const WINDOWS = [{l:'7D',d:7},{l:'30D',d:30},{l:'60D',d:60},{l:'90D',d:90},{l:'ALL',d:365}]

export default function Timeline() {
  const [days, setDays] = useState(30)
  const [sa, setSA] = useState(true)
  const [sm, setSM] = useState(true)
  const [si, setSI] = useState(true)
  const { data, loading } = useApi(`/api/timeline?days=${days}`, [days])

  const chart = useMemo(()=>(data?.timeline||[]).map(d=>({
    date:(d.day||'').slice(5),avg:+(d.risk_score_avg||0).toFixed(2),
    max:+(d.risk_score_max||0).toFixed(2),incidents:d.n_anomalies||0
  })),[data])

  const stats = useMemo(()=>{
    if(!chart.length)return null
    const avgs=chart.map(d=>d.avg),maxs=chart.map(d=>d.max),incs=chart.map(d=>d.incidents)
    const peakDay=chart.reduce((a,b)=>b.max>a.max?b:a,chart[0])
    return{peak:Math.max(...maxs).toFixed(1),peakDate:peakDay?.date||'—',mean:(avgs.reduce((a,b)=>a+b,0)/avgs.length).toFixed(1),totalInc:incs.reduce((a,b)=>a+b,0)}
  },[chart])

  const toggles=[
    {key:'avg',lbl:'Avg Risk',c:'#5b8df6',s:sa,set:setSA},
    {key:'max',lbl:'Max Risk',c:'#fb923c',s:sm,set:setSM},
    {key:'inc',lbl:'Incidents',c:'rgba(251,191,36,.7)',s:si,set:setSI},
  ]

  return(
    <div className="page">
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:20,flexWrap:'wrap',gap:12}}>
        <div className="sec" style={{marginBottom:0}}>
          <div className="sec-t">Timeline Analysis</div>
          <div className="sec-s">Rolling risk score · entire monitored population</div>
        </div>
        <div className="tab-row">
          {WINDOWS.map(w=><button key={w.d} className={`tab${days===w.d?' active':''}`} onClick={()=>setDays(w.d)}>{w.l}</button>)}
        </div>
      </div>

      {stats&&(
        <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:18}}>
          {[['PEAK SCORE',stats.peak,'var(--red)'],['AVG MEAN',stats.mean,'var(--blue)'],['INCIDENTS',stats.totalInc,'var(--orange)'],['PEAK DATE',stats.peakDate?.slice(0,5)||'—','var(--t2)']].map(([l,v,c])=>(
            <div key={l} className="scard c-blue" style={{paddingTop:16,paddingBottom:16}}>
              <div className="s-lbl">{l}</div>
              <div style={{fontSize:24,fontFamily:"'JetBrains Mono',monospace",fontWeight:700,color:c,marginTop:4}}>{v}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{display:'flex',gap:8,marginBottom:14}}>
        {toggles.map(({key,lbl,c,s,set})=>(
          <button key={key} onClick={()=>set(v=>!v)} style={{
            padding:'5px 14px',borderRadius:6,
            border:`1px solid ${s?c:'var(--line)'}`,
            background:s?`${c}18`:'none',
            color:s?c:'var(--t3)',fontFamily:"'JetBrains Mono',monospace",fontSize:11,
            display:'flex',alignItems:'center',gap:6,transition:'all .15s'}}>
            <div style={{width:10,height:2,background:s?c:'var(--t3)',borderRadius:1}}/>
            {lbl}
          </button>
        ))}
      </div>

      <div className="card">
        <div className="card-h">
          <span className="card-t">Risk Timeline — {days} days</span>
          <span style={{fontFamily:"'JetBrains Mono',monospace",fontSize:10,color:'var(--t3)'}}>{chart.length} data points</span>
        </div>
        <div style={{padding:'18px 10px 10px'}}>
          {loading?<Loading/>:!chart.length?<Empty/>:(
            <ResponsiveContainer width="100%" height={310}>
              <ComposedChart data={chart} margin={{top:4,right:10,left:-24,bottom:0}}>
                <defs>
                  <linearGradient id="tg" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#5b8df6" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#5b8df6" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3"/>
                <XAxis dataKey="date" tick={{fill:'var(--t3)',fontSize:10,fontFamily:"'JetBrains Mono',monospace"}} tickLine={false} axisLine={false} interval="preserveStartEnd" tickFormatter={v=>v?.slice(0,5)}/>
                <YAxis yAxisId="s" domain={[0,100]} tick={{fill:'var(--t3)',fontSize:10,fontFamily:"'JetBrains Mono',monospace"}} tickLine={false} axisLine={false}/>
                <YAxis yAxisId="i" orientation="right" tick={{fill:'var(--t3)',fontSize:10,fontFamily:"'JetBrains Mono',monospace"}} tickLine={false} axisLine={false}/>
                <Tooltip content={<ChartTooltip/>}/>
                <ReferenceLine yAxisId="s" y={85} stroke="var(--red)"    strokeDasharray="5 4" strokeWidth={0.8}/>
                <ReferenceLine yAxisId="s" y={70} stroke="var(--orange)" strokeDasharray="5 4" strokeWidth={0.8}/>
                <ReferenceLine yAxisId="s" y={40} stroke="var(--cyan)"   strokeDasharray="5 4" strokeWidth={0.6}/>
                {si&&<Bar yAxisId="i" dataKey="incidents" name="Incidents" fill="rgba(251,191,36,.18)" stroke="rgba(251,191,36,.4)" strokeWidth={0.5} barSize={6} radius={[2,2,0,0]}/>}
                {sm&&<Line yAxisId="s" type="monotone" dataKey="max" name="Max Risk" stroke="#fb923c" strokeWidth={1.5} dot={false} strokeDasharray="5 3"/>}
                {sa&&<Area yAxisId="s" type="monotone" dataKey="avg" name="Avg Risk" stroke="#5b8df6" strokeWidth={2.5} fill="url(#tg)" dot={false}/>}
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {!loading&&chart.length>0&&(
        <div className="card" style={{marginTop:14}}>
          <div className="card-h"><span className="card-t">Incident Calendar</span></div>
          <div style={{padding:'14px 18px',display:'flex',flexWrap:'wrap',gap:3}}>
            {chart.slice(-60).map((d,i)=>{
              const c=d.max>=85?`rgba(248,113,113,${.3+Math.min(.6,(d.incidents||1)/5*.6)})`:d.max>=70?`rgba(251,146,60,${.25+(d.avg/100)*.3})`:d.avg>15?`rgba(91,141,246,${.1+(d.avg/100)*.15})`:'rgba(255,255,255,.04)'
              return<div key={i} title={`${d.date}: max=${d.max.toFixed(1)}, avg=${d.avg.toFixed(1)}`}
                style={{width:13,height:13,borderRadius:2,background:c,transition:'transform .1s',cursor:'default'}}
                onMouseOver={e=>e.currentTarget.style.transform='scale(1.5)'}
                onMouseOut={e=>e.currentTarget.style.transform=''}/>
            })}
          </div>
          <div style={{padding:'0 18px 12px',fontSize:10,color:'var(--t3)',fontFamily:"'JetBrains Mono',monospace"}}>
            Each square = 1 day · Red = HIGH/CRITICAL anomaly detected
          </div>
        </div>
      )}
    </div>
  )
}
