import { useState, useEffect, useCallback, useRef } from 'react'

const BASE = ''

async function apiFetch(path, options = {}) {
  const res = await fetch(BASE + path, options)
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`)
  return res.json()
}

export function useApi(path, deps = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetch_ = useCallback(async () => {
    if (!path) return
    setLoading(true)
    setError(null)
    try {
      const d = await apiFetch(path)
      setData(d)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [path, ...deps])

  useEffect(() => { fetch_() }, [fetch_])

  return { data, loading, error, refetch: fetch_ }
}

export function usePolling(path, intervalMs = 30000) {
  const { data, loading, error, refetch } = useApi(path)
  useEffect(() => {
    const id = setInterval(refetch, intervalMs)
    return () => clearInterval(id)
  }, [refetch, intervalMs])
  return { data, loading, error, refetch }
}

export { apiFetch }
