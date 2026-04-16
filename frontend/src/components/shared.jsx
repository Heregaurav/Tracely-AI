/* Shared UI primitives */
const TC = {
  CRITICAL:'var(--red)', HIGH:'var(--orange)',
  MEDIUM:'var(--yellow)', LOW:'var(--cyan)', NORMAL:'var(--green)'
}
const BG = {
  CRITICAL:'rgba(248,113,113,.15)', HIGH:'rgba(251,146,60,.15)',
  MEDIUM:'rgba(251,191,36,.12)',    LOW:'rgba(34,211,238,.1)',  NORMAL:'rgba(52,211,153,.1)'
}

export function Badge({ tier = 'NORMAL' }) {
  return <span className={`badge ${tier}`}>{tier}</span>
}

export function RiskBar({ score = 0, width = 72 }) {
  const c = score>=95?'var(--red)':score>=85?'var(--orange)':score>=70?'var(--yellow)':score>=40?'var(--cyan)':'var(--green)'
  return (
    <div className="rbar" style={{ width }}>
      <div className="rbar-f" style={{ width:`${Math.min(100,score)}%`, background:c }} />
    </div>
  )
}

export function ScoreDonut({ score = 0, size = 76 }) {
  const r = (size - 10) / 2
  const circ = 2 * Math.PI * r
  const pct  = Math.min(100, Math.max(0, score))
  const dash = (pct / 100) * circ
  const tier = pct>=95?'CRITICAL':pct>=85?'HIGH':pct>=70?'MEDIUM':pct>=40?'LOW':'NORMAL'
  const c    = TC[tier]
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={size/2} cy={size/2} r={r} fill="none"
        stroke="rgba(255,255,255,.05)" strokeWidth="7" />
      <circle cx={size/2} cy={size/2} r={r} fill="none"
        stroke={c} strokeWidth="7"
        strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
        transform={`rotate(-90 ${size/2} ${size/2})`}
        style={{ transition:'stroke-dasharray .6s' }} />
      <text x={size/2} y={size/2+1} textAnchor="middle" dominantBaseline="middle"
        fill={c} fontSize={size*.22} fontFamily="'JetBrains Mono',monospace" fontWeight="700">
        {Math.round(pct)}
      </text>
    </svg>
  )
}

export function Avatar({ name = '', tier = 'NORMAL', size = 34 }) {
  const initials = (name || '?').split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase()
  const c = TC[tier] || TC.NORMAL
  const bg = BG[tier] || BG.NORMAL
  return (
    <div className="av" style={{
      width:size, height:size, fontSize:size*.33,
      color:c, background:bg, border:`1.5px solid ${c}`,
    }}>
      {initials}
    </div>
  )
}

export function TrendBadge({ dir }) {
  const map = { up:['↑','var(--red)'], down:['↓','var(--green)'], stable:['→','var(--t3)'] }
  const [icon, color] = map[dir] || map.stable
  return <span style={{ color, fontSize:13, fontWeight:700 }}>{icon}</span>
}

export function Loading({ text = 'Loading...' }) {
  return (
    <div className="loading">
      <div className="spin" />
      <span style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:11 }}>{text}</span>
    </div>
  )
}

export function Empty({ text = 'No data' }) {
  return (
    <div className="empty">
      <svg width="32" height="32" viewBox="0 0 32 32" fill="none"
        stroke="var(--t4)" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="16" cy="16" r="12"/>
        <line x1="16" y1="10" x2="16" y2="17"/>
        <circle cx="16" cy="21" r=".8" fill="var(--t4)" stroke="none"/>
      </svg>
      <span>{text}</span>
    </div>
  )
}

export function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="ct">
      <div className="ct-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color||'var(--t1)', marginTop:3, fontSize:12 }}>
          {p.name}: <strong>{typeof p.value==='number' ? p.value.toFixed(1) : p.value}</strong>
        </div>
      ))}
    </div>
  )
}
