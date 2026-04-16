import { useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { Loading, Empty, Badge } from '../components/shared'
import { ShieldAlert, Users, TrendingUp, Building2 } from 'lucide-react'

const riskColor = score =>
  score >= 70 ? 'var(--red)' :
  score >= 50 ? 'var(--orange)' :
  score >= 30 ? 'var(--yellow)' :
  score >= 15 ? 'var(--cyan)' :
  'var(--green)'

const riskTier = score =>
  score >= 70 ? 'CRITICAL' :
  score >= 50 ? 'HIGH' :
  score >= 30 ? 'MEDIUM' :
  score >= 15 ? 'LOW' :
  'NORMAL'

function StatCard({ icon: Icon, label, value, accent, sub }) {
  return (
    <div className="feature-panel">
      <div className="feature-panel-h">
        <div className="feature-icon" style={{ color: accent, borderColor: `${accent}40`, background: `${accent}1a` }}>
          <Icon size={16} />
        </div>
        <div className="feature-label">{label}</div>
      </div>
      <div className="feature-value" style={{ color: accent }}>{value}</div>
      <div className="feature-sub">{sub}</div>
    </div>
  )
}

export default function Departments() {
  const { data, loading } = useApi('/api/departments')
  const depts = useMemo(
    () => [...(data?.departments || [])]
      .filter(d => d?.department)
      .sort((a, b) => (b.avg_risk || 0) - (a.avg_risk || 0)),
    [data]
  )

  const totals = useMemo(() => {
    const totalUsers = depts.reduce((sum, d) => sum + (d.user_count || 0), 0)
    const avgRisk = depts.length ? depts.reduce((sum, d) => sum + (d.avg_risk || 0), 0) / depts.length : 0
    const hotspot = depts[0]
    const mostCritical = [...depts].sort((a, b) => (b.critical_count || 0) - (a.critical_count || 0))[0]
    return { totalUsers, avgRisk, hotspot, mostCritical }
  }, [depts])

  if (loading) return <div className="page"><Loading text="Analyzing departments…" /></div>

  return (
    <div className="page">
      <div className="hero">
        <div>
          <div className="hero-kicker">Department Intelligence</div>
          <h1 className="hero-title">Where organizational risk is concentrating right now</h1>
          <p className="hero-copy">
            Compare department-level exposure, highlight hotspots, and spot teams whose aggregate behavior is drifting out of baseline.
          </p>
        </div>
        <div className="hero-chip">
          <Building2 size={14} />
          {depts.length} departments monitored
        </div>
      </div>

      {!depts.length ? <Empty text="No department data available" /> : (
        <>
          <div className="feature-grid" style={{ marginBottom: 18 }}>
            <StatCard
              icon={Users}
              label="Users Covered"
              value={totals.totalUsers}
              accent="var(--blue)"
              sub="Active staff represented in department rollups"
            />
            <StatCard
              icon={TrendingUp}
              label="Avg Dept Risk"
              value={totals.avgRisk.toFixed(1)}
              accent="var(--cyan)"
              sub="Mean department risk across the organization"
            />
            <StatCard
              icon={ShieldAlert}
              label="Primary Hotspot"
              value={totals.hotspot?.department || '—'}
              accent={riskColor(totals.hotspot?.avg_risk || 0)}
              sub={totals.hotspot ? `${totals.hotspot.avg_risk.toFixed(1)} avg risk` : 'No hotspot available'}
            />
            <StatCard
              icon={Building2}
              label="Most Critical Cases"
              value={totals.mostCritical?.department || '—'}
              accent="var(--orange)"
              sub={totals.mostCritical ? `${totals.mostCritical.critical_count || 0} critical users` : 'No critical users'}
            />
          </div>

          <div className="g2">
            <div className="card">
              <div className="card-h"><span className="card-t">Department Hotspots</span></div>
              <div className="card-b">
                {depts.slice(0, 6).map((d, index) => (
                  <div key={d.department} className="dept-row">
                    <div className="dept-rank">{String(index + 1).padStart(2, '0')}</div>
                    <div className="dept-main">
                      <div className="dept-name-line">
                        <span className="dept-name">{d.department}</span>
                        <Badge tier={riskTier(d.avg_risk || 0)} />
                      </div>
                      <div className="dept-subline">
                        {(d.user_count || 0)} users · {(d.critical_count || 0)} critical · {(d.high_count || 0)} high
                      </div>
                      <div className="dept-track">
                        <div
                          className="dept-fill"
                          style={{ width: `${Math.min(100, d.avg_risk || 0)}%`, background: riskColor(d.avg_risk || 0) }}
                        />
                      </div>
                    </div>
                    <div className="dept-score" style={{ color: riskColor(d.avg_risk || 0) }}>
                      {(d.avg_risk || 0).toFixed(1)}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <div className="card-h"><span className="card-t">Operational Readout</span></div>
              <div className="card-b">
                {depts.slice(0, 5).map(d => (
                  <div key={d.department} className="signal-card">
                    <div className="signal-top">
                      <div>
                        <div className="signal-title">{d.department}</div>
                        <div className="signal-caption">Max risk {(d.max_risk || 0).toFixed(1)}</div>
                      </div>
                      <div className="signal-badge" style={{ color: riskColor(d.avg_risk || 0), borderColor: `${riskColor(d.avg_risk || 0)}55` }}>
                        {(d.avg_risk || 0).toFixed(1)}
                      </div>
                    </div>
                    <div className="signal-meta">
                      <span>{d.user_count || 0} users</span>
                      <span>{d.high_count || 0} high</span>
                      <span>{d.critical_count || 0} critical</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="card" style={{ overflowX: 'auto' }}>
            <div className="card-h"><span className="card-t">Full Department Report</span></div>
            <table className="tbl">
              <thead>
                <tr>
                  <th>DEPARTMENT</th>
                  <th>USERS</th>
                  <th>AVG RISK</th>
                  <th>MAX RISK</th>
                  <th>CRITICAL</th>
                  <th>HIGH</th>
                  <th>TIER</th>
                  <th>PROFILE</th>
                </tr>
              </thead>
              <tbody>
                {depts.map(d => (
                  <tr key={d.department}>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ width: 4, height: 22, borderRadius: 999, background: riskColor(d.avg_risk || 0), flexShrink: 0 }} />
                        <div>
                          <div style={{ fontWeight: 600, color: 'var(--t1)' }}>{d.department}</div>
                          <div style={{ fontSize: 11, color: 'var(--t3)' }}>Org risk cluster</div>
                        </div>
                      </div>
                    </td>
                    <td className="mono">{d.user_count || 0}</td>
                    <td><span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 15, fontWeight: 700, color: riskColor(d.avg_risk || 0) }}>{(d.avg_risk || 0).toFixed(1)}</span></td>
                    <td><span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 13, color: riskColor(d.max_risk || 0) }}>{(d.max_risk || 0).toFixed(1)}</span></td>
                    <td style={{ fontFamily: "'JetBrains Mono',monospace", color: (d.critical_count || 0) > 0 ? 'var(--red)' : 'var(--t3)' }}>{d.critical_count || 0}</td>
                    <td style={{ fontFamily: "'JetBrains Mono',monospace", color: (d.high_count || 0) > 0 ? 'var(--orange)' : 'var(--t3)' }}>{d.high_count || 0}</td>
                    <td><Badge tier={riskTier(d.avg_risk || 0)} /></td>
                    <td>
                      <div className="dept-track" style={{ width: 92 }}>
                        <div
                          className="dept-fill"
                          style={{ width: `${Math.min(100, d.avg_risk || 0)}%`, background: riskColor(d.avg_risk || 0) }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
