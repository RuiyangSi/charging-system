// 后端 API 封装 + 轮询 Hook
import { useEffect, useRef, useState } from 'react'

const BASE = '/api'

export async function api(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = body.detail || JSON.stringify(body)
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

export const get = (p) => api(p)
export const post = (p, body) => api(p, { method: 'POST', body: JSON.stringify(body ?? {}) })
export const put = (p, body) => api(p, { method: 'PUT', body: JSON.stringify(body ?? {}) })
export const del = (p) => api(p, { method: 'DELETE' })

/** 周期轮询：返回 {data, error, refresh}；fetcher 抛错时保留上次数据并记录错误。 */
export function usePoll(fetcher, ms = 1000, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const fnRef = useRef(fetcher)
  fnRef.current = fetcher
  const [tickKey, setTickKey] = useState(0)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const d = await fnRef.current()
        if (alive) { setData(d); setError(null) }
      } catch (e) {
        if (alive) setError(e.message)
      }
    }
    tick()
    const id = setInterval(tick, ms)
    return () => { alive = false; clearInterval(id) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, tickKey, ...deps])

  return { data, error, refresh: () => setTickKey(k => k + 1) }
}

export const fmtH = (h) => {
  if (h == null) return '—'
  const totalSeconds = Math.max(0, Math.round(Number(h) * 3600))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}分${String(seconds).padStart(2, '0')}秒`
}

export const yuan = (v) => (v == null ? '—' : `¥ ${Number(v).toFixed(2)}`)

// 固定两位小数显示（电量等），保留 1.00 / 0.80 这类尾零，与验收表书写格式一致
export const num2 = (v) => (v == null ? '—' : Number(v).toFixed(2))
