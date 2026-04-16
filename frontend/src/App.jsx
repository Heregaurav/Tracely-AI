import { useState, useEffect } from 'react'
import { LayoutDashboard, AlertTriangle, Users, BarChart2, TrendingUp, Building2, FileText, RefreshCw, MoonStar, SunMedium } from 'lucide-react'
import { usePolling } from './hooks/useApi'
import Overview    from './pages/Overview'
import Threats     from './pages/Threats'
import UsersList   from './pages/Users'
import Heatmap     from './pages/Heatmap'
import Timeline    from './pages/Timeline'
import Departments from './pages/Departments'
import Reports     from './pages/Reports'

const PAGES = {
  overview:    { label:'Overview',      Component:Overview,    Icon:LayoutDashboard },
  threats:     { label:'Threats',       Component:Threats,     Icon:AlertTriangle   },
  users:       { label:'Users',         Component:UsersList,   Icon:Users           },
  heatmap:     { label:'Risk Heatmap',  Component:Heatmap,     Icon:BarChart2       },
  timeline:    { label:'Timeline',      Component:Timeline,    Icon:TrendingUp      },
  departments: { label:'Departments',   Component:Departments, Icon:Building2       },
  reports:     { label:'Reports',       Component:Reports,     Icon:FileText        },
}

const NAV_GROUPS = [
  { label:'MONITOR',   ids:['overview','threats','users'] },
  { label:'ANALYTICS', ids:['heatmap','timeline','departments'] },
  { label:'SYSTEM',    ids:['reports'] },
]

function threatLevel(s) {
  if (!s) return 'ASSESSING'
  if ((s.critical_users||0) > 0) return 'CRITICAL'
  if ((s.high_risk_users||0) > 2) return 'HIGH'
  if ((s.open_alerts||0) > 5)    return 'MEDIUM'
  if ((s.open_alerts||0) > 0)    return 'LOW'
  return 'NORMAL'
}

export default function App() {
  const [page, setPage] = useState('overview')
  const [clock, setClock] = useState('')
  const [theme, setTheme] = useState(() => localStorage.getItem('tracely-theme') || 'dark')
  const { data:stats, refetch } = usePolling('/api/stats', 30000)

  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString('en-GB'))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('tracely-theme', theme)
  }, [theme])

  const level = threatLevel(stats)
  const badge = (stats?.tier_distribution?.CRITICAL||0) + (stats?.tier_distribution?.HIGH||0)
  const { Component } = PAGES[page] || PAGES.overview
  const isLight = theme === 'light'

  return (
    <div className="app">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sb-brand">
          <div className="sb-logo">
            <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.14em', color: '#fff', marginLeft: 2 }}>TA</span>
          </div>
          <div>
            <div className="sb-name">Tracely AI</div>
            <div className="sb-ver">Bring Imposter Down</div>
          </div>
        </div>

        <nav className="sb-nav">
          {NAV_GROUPS.map(({ label, ids }) => (
            <div key={label}>
              <div className="sb-group">{label}</div>
              {ids.map(id => {
                const { label:lbl, Icon } = PAGES[id]
                return (
                  <button
                    key={id}
                    className={`sb-item${page===id?' active':''}`}
                    onClick={() => setPage(id)}
                  >
                    <Icon size={14} />
                    {lbl}
                    {id==='threats' && badge>0 && (
                      <span className="sb-count">{badge}</span>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="sb-foot">
          <div className="sb-live">
            <div className="sb-dot" />
            LIVE MONITORING
          </div>
          <div className="sb-info">
            {stats
              ? `${stats.total_users} users · ${stats.open_alerts} alerts`
              : 'Connecting...'}
          </div>
        </div>
      </aside>

      {/* ── Main ── */}
      <div className="main">
        <header className="topbar">
          <div className="topbar-l">
            <span className="pg-title">{PAGES[page]?.label}</span>
          </div>
          <div className="topbar-r">
            <div className={`tpill ${level}`}>
              <div
                className="tpill-dot"
                style={{ animation: ['CRITICAL','HIGH'].includes(level) ? 'glow 1s infinite' : 'none' }}
              />
              {level}
            </div>
            <button
              className={`theme-toggle${isLight ? ' light' : ''}`}
              onClick={() => setTheme(isLight ? 'dark' : 'light')}
              title={isLight ? 'Switch to dark mode' : 'Switch to light mode'}
              aria-label={isLight ? 'Switch to dark mode' : 'Switch to light mode'}
            >
              <span className="theme-toggle-track">
                <span className="theme-toggle-thumb">
                  {isLight ? <SunMedium size={12} /> : <MoonStar size={12} />}
                </span>
              </span>
              <span className="theme-toggle-label">{isLight ? 'Soft Light' : 'Night Mode'}</span>
            </button>
            <span className="clock">{clock}</span>
            <button className="icon-btn" onClick={refetch} title="Refresh data">
              <RefreshCw size={13} />
            </button>
          </div>
        </header>

        <Component onNavigate={setPage} />
      </div>
    </div>
  )
}
