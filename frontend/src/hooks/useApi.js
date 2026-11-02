import { useState, useEffect, useCallback, useRef } from 'react'

export const BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
export async function apiFetch(path, options = {}) {
  const res = await fetch(BASE + path, { ...options, credentials: 'omit' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.error || `API ${path} → ${res.status}`)
  }
  return data
}

export function useApi(path) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const sequence = useRef(0)
  const refetch = useCallback(async () => {
    if (!path) return
    const current = ++sequence.current
    setLoading(true)
    setError(null)
    try { const result = await apiFetch(path); if (current === sequence.current) setData(result) }
    catch (e) { if (current === sequence.current) setError(e.message) }
    finally { if (current === sequence.current) setLoading(false) }
  }, [path])
  useEffect(() => {
    let active = true
    Promise.resolve().then(() => { if (active) refetch() })
    return () => {
      active = false
      // This ref is a request generation counter; invalidate all pending responses.
      sequence.current += 1
    }
  }, [refetch])
  return { data, loading, error, refetch }
}

export function usePolling(path, intervalMs = 30000) {
  const result = useApi(path)
  useEffect(() => {
    if (!path) return
    const id = setInterval(result.refetch, intervalMs)
    return () => clearInterval(id)
  }, [path, intervalMs, result.refetch])
  return result
}
