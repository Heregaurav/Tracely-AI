import { useState } from 'react'
import { ArrowUpRight, Bell, CalendarDays, ChevronLeft, ChevronRight, Clock3, RefreshCw } from 'lucide-react'
import { apiFetch, usePolling } from '../hooks/useApi'
import { Badge, Empty, Loading } from '../components/shared'

const TIERS = ['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'NORMAL']
const COLORS = { CRITICAL: 'var(--red)', HIGH: 'var(--orange)', MEDIUM: 'var(--yellow)', LOW: 'var(--cyan)', NORMAL: 'var(--green)' }
const time = value => value?.slice(11, 16) || '—'

function HourDetail({ hour, onNavigate, refreshHours }) {
  const { data, loading, error, refetch } = usePolling(`/api/hours/${hour.window_index}`, 30000)
  const [tier, setTier] = useState('ALL')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(null)
  const [message, setMessage] = useState('')
  const records = (data?.observations || []).filter(row => (tier === 'ALL' || row.risk_tier === tier) && row.user.toLowerCase().includes(search.toLowerCase()))

  const updateStatus = async (alert, next) => {
    setBusy(alert.alert_id); setMessage('')
    try {
      await apiFetch(`/api/threats/${alert.alert_id}/status`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: next, version: alert.version }),
      })
    } catch (failure) { setMessage(failure.message) }
    finally { setBusy(null); refetch(); refreshHours() }
  }

  if (loading && !data) return <Loading text="Loading stored hour…" />
  if (error) return <div className="callout" role="alert">{error}<button className="btn btn-sm" onClick={refetch}>Retry</button></div>
  if (!data) return null
  const cards = [
    ['Observed accounts', data.observed_accounts, 'var(--blue)'],
    ['Flagged user-hours', data.flagged_accounts, 'var(--orange)'],
    ['Open investigations', data.open_alerts, 'var(--red)'],
    ['Observed events', data.observed_events, 'var(--cyan)'],
    ['Average index', data.average_risk?.toFixed(2), 'var(--green)'],
  ]
  return <>
    <div className="hourly-summary">
      {cards.map(([label, value, color]) => <div className="scard" key={label}><span className="s-lbl">{label}</span><strong style={{ color }}>{value}</strong><small>This selected hour only</small></div>)}
    </div>
    <div className="hourly-content">
      <section className="card">
        <div className="card-h"><span className="card-t">Account risk in this hour</span><span className="mono">{records.length} / {data.observed_accounts} accounts</span></div>
        <div className="card-b hourly-table-controls">
          <input className="search" aria-label="Find account in selected hour" placeholder="Find account…" value={search} onChange={event => setSearch(event.target.value)} />
          <div className="pills">{TIERS.map(value => <button className={`pill${tier === value ? ' active' : ''}`} key={value} onClick={() => setTier(value)}>{value}{value !== 'ALL' && ` ${data.tier_distribution[value] || 0}`}</button>)}</div>
        </div>
        <div className="hourly-table-scroll">
          {!records.length ? <Empty text="No accounts match this hour's filters" /> : <table className="tbl"><thead><tr><th>ACCOUNT</th><th>HOUR RISK INDEX</th><th>TIER</th><th>EVENTS</th><th>ALERT</th></tr></thead><tbody>
            {records.map(row => <tr key={row.user}>
              <td><code className="mono">{row.user}</code></td>
              <td><strong style={{ color: COLORS[row.risk_tier] }}>{row.risk_score.toFixed(2)}</strong></td>
              <td><Badge tier={row.risk_tier} /></td><td>{row.explanation.event_count}</td>
              <td>{row.alert_id ? <button className="btn btn-sm" onClick={() => onNavigate('threats', { hour: hour.window_index, userId: row.user })}>{row.alert_status.replaceAll('_', ' ')} <ArrowUpRight size={12} /></button> : <span className="hourly-muted">{row.risk_score >= data.alert_threshold ? 'Flagged · stored alert unavailable' : 'Below alert threshold'}</span>}</td>
            </tr>)}
          </tbody></table>}
        </div>
        <div className="hourly-footnote">Risk belongs to this account-hour, not the user's historical peak. HIGH and CRITICAL hours trigger an alert at index ≥ {data.alert_threshold.toFixed(2)}.</div>
      </section>
      <aside className="card">
        <div className="card-h"><span className="card-t"><Bell size={14} /> Hourly alerts</span><span>{data.alerts.length}</span></div>
        {message && <p className="callout" role="alert">{message}</p>}
        {!data.alerts.length ? <Empty text={data.flagged_accounts ? 'Flagged hours have no stored alerts; check publication' : 'No HIGH or CRITICAL user-hours in this hour'} /> : <div className="hourly-alert-list">{data.alerts.map(alert => <article className="hourly-alert" key={alert.alert_id}>
          <div className="hourly-alert-heading"><code>{alert.user_id}</code><Badge tier={alert.risk_tier} /></div>
          <p><strong style={{ color: COLORS[alert.risk_tier] }}>{alert.risk_score.toFixed(2)}</strong> index · {time(hour.window_start)}–{time(hour.window_end)}</p>
          <p className="hourly-muted">{alert.explanation.event_count} observed events · {alert.status.replaceAll('_', ' ')}</p>
          <div className="hourly-alert-actions">
            {alert.status === 'OPEN' && <button className="btn btn-sm" disabled={busy === alert.alert_id} onClick={() => updateStatus(alert, 'IN_PROGRESS')}>Investigate</button>}
            {alert.status !== 'RESOLVED' && <button className="btn btn-sm" disabled={busy === alert.alert_id} onClick={() => updateStatus(alert, 'RESOLVED')}>Resolve</button>}
            <button className="btn btn-sm" onClick={() => onNavigate('threats', { hour: hour.window_index, userId: alert.user_id })}>Evidence <ArrowUpRight size={12} /></button>
          </div>
        </article>)}</div>}
        <div className="hourly-footnote">An alert is a review request, not proof of malicious intent. Status changes update the existing alert and its audit history.</div>
      </aside>
    </div>
  </>
}

export default function HourlyMonitor({ onNavigate, hour: initialHour }) {
  const { data, loading, error, refetch } = usePolling('/api/hours?days=365', 30000)
  const [selected, setSelected] = useState(initialHour == null ? null : Number(initialHour))
  const hours = data?.hours || []
  const active = selected == null ? hours.at(-1) : hours.find(item => item.window_index === selected)
  const days = [...new Set(hours.map(item => item.window_start.slice(0, 10)))].reverse()
  const date = active?.window_start.slice(0, 10) || days[0] || ''
  const dayHours = hours.filter(item => item.window_start.startsWith(date))
  const position = active ? hours.findIndex(item => item.window_index === active.window_index) : -1
  const selectHour = index => {
    setSelected(index)
    const url = new URL(window.location.href)
    if (index == null) url.searchParams.delete('hour'); else url.searchParams.set('hour', String(index))
    const params = { ...(window.history.state?.params || {}) }
    if (index == null) delete params.hour; else params.hour = index
    window.history.replaceState({ ...window.history.state, page: 'hourly', params }, '', url)
  }
  return <div className="page hourly-page">
    <header className="hourly-heading"><div><div className="hourly-kicker"><Clock3 size={14} /> STORED HOURLY OBSERVATIONS</div><h1>Hourly Monitor</h1><p>Choose an hour. Review its accounts, risk levels and alerts together.</p></div><button className="btn" onClick={refetch}><RefreshCw size={14} /> Refresh hours</button></header>
    {error && <div className="callout" role="alert">{error}</div>}
    {loading && !data ? <Loading /> : !hours.length ? <Empty text="No published hourly observations available" /> : <>
      <section className="card hourly-picker">
        <div className="hourly-picker-heading"><label><CalendarDays size={15} /> Observation date<select aria-label="Observation date" value={date} onChange={event => selectHour(hours.filter(item => item.window_start.startsWith(event.target.value)).at(-1).window_index)}>{days.map(day => <option key={day}>{day}</option>)}</select></label>
          <label className="hourly-follow"><input type="checkbox" checked={selected == null} onChange={event => selectHour(event.target.checked ? null : active?.window_index)} /> Follow latest stored hour</label>
          <div className="hourly-stepper"><button className="icon-btn" aria-label="Previous observed hour" disabled={position <= 0} onClick={() => selectHour(hours[position - 1].window_index)}><ChevronLeft size={17} /></button><button className="icon-btn" aria-label="Next observed hour" disabled={position < 0 || position >= hours.length - 1} onClick={() => selectHour(hours[position + 1].window_index)}><ChevronRight size={17} /></button></div>
        </div>
        <div className="hourly-hours" aria-label="Hours in observation date">{Array.from({ length: 24 }, (_, index) => {
          const label = String(index).padStart(2, '0') + ':00'
          const stored = dayHours.find(item => item.window_start.slice(11, 13) === label.slice(0, 2))
          return <button key={label} disabled={!stored} aria-pressed={!!stored && stored.window_index === active?.window_index} aria-label={`${label} — ${stored ? `${stored.observed_accounts} accounts, ${stored.alerts} alerts` : 'no stored observations'}`} className={`hourly-hour${stored?.window_index === active?.window_index ? ' selected' : ''}`} style={stored ? { '--hour-accent': COLORS[stored.peak_tier] } : undefined} onClick={() => selectHour(stored.window_index)}><strong>{label}</strong><span>{stored ? `${stored.alerts} alert${stored.alerts === 1 ? '' : 's'}` : 'No data'}</span><small>{stored ? `${stored.observed_accounts} accounts` : 'Unobserved'}</small></button>
        })}</div>
        <p className="hourly-footnote">Source wall-clock; timezone not supplied. Grey hours have no stored observations. They are not classified as normal. New stored hours are checked every 30 seconds.</p>
      </section>
      {active ? <>
        <div className="hourly-selected-heading"><div><h2>{date} · {time(active.window_start)}–{time(active.window_end)}</h2><p>{data.model_name} · one closed hour · end time excluded</p></div><button className="btn" onClick={() => onNavigate('threats', { hour: active.window_index })}>Review this hour's alerts <ArrowUpRight size={14} /></button></div>
        <HourDetail key={active.window_index} hour={active} onNavigate={onNavigate} refreshHours={refetch} />
      </> : <div className="callout" role="alert">The selected hour has no stored observations in this range. <button className="btn" onClick={() => selectHour(null)}>Show latest stored hour</button></div>}
      <p className="hourly-footnote">This view uses published scores and existing alerts. New Data Inference keeps raw-import results in its separate stream. This is stored-data review, not a live telemetry collector.</p>
    </>}
  </div>
}
