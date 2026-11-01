import { useEffect, useState } from 'react'
import { apiFetch, BASE, setCsrfToken } from '../hooks/useApi'
import { AuthContext } from '../hooks/authContext'

export default function SessionGate({ children }) {
  const [identity, setIdentity] = useState(null)
  const [mode, setMode] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    apiFetch('/api/auth/options').then(setMode).catch(e => setError(e.message))
    apiFetch('/api/auth/session').then(data => { setCsrfToken(data.csrf_token); setIdentity(data) })
      .catch(() => {}).finally(() => setLoading(false))
    const expired = () => { setIdentity(null); setCsrfToken('') }
    window.addEventListener('session-expired', expired)
    return () => window.removeEventListener('session-expired', expired)
  }, [])
  const login = async e => {
    e.preventDefault(); setError('')
    const fields = new FormData(e.currentTarget)
    try {
      const data = await apiFetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: fields.get('username'), password: fields.get('password') }) })
      setCsrfToken(data.csrf_token); setIdentity(data)
    } catch (err) { setError(err.message) }
  }
  const logout = async () => {
    try { await apiFetch('/api/auth/logout', { method: 'POST' }); setIdentity(null); setCsrfToken('') }
    catch (err) { setError(err.message) }
  }
  if (loading) return <div className="page">Checking session…</div>
  if (!identity) return <div className="page" style={{ maxWidth: 480, margin: '10vh auto' }}>
    <div className="card"><div className="card-b">
      <h1>Tracely AI</h1><p>Sign in to review behavioral anomaly evidence.</p>
      {error && <p role="alert">{error}</p>}
      {mode?.development ? <form onSubmit={login} style={{ display: 'grid', gap: 16, marginTop: 20 }}>
        <label>Username<input className="search" name="username" autoComplete="username" required /></label>
        <label>Password<input className="search" type="password" name="password" autoComplete="current-password" required /></label>
        <button className="btn btn-primary" type="submit">Sign in</button>
        <p>Development authentication. Accounts are configured by your local administrator.</p>
      </form> : mode?.oidc ? <a className="btn" href={BASE + '/api/auth/oidc'}>Organization sign in</a> : <p>Authentication service unavailable.</p>}
    </div></div>
  </div>
  return <AuthContext.Provider value={identity}>
    <div style={{ position: 'fixed', bottom: 8, right: 16, zIndex: 1000 }}>
      <button className="btn btn-sm" onClick={logout}>{identity.actor} · {identity.role} · Sign out</button>
      {error && <span role="alert">{error}</span>}
    </div>
    {children}
  </AuthContext.Provider>
}
