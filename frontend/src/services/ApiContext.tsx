import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { getCatalog, getHealth, listExperiments } from './api'
import type { ApiCatalog, ApiExperimentSummary, ApiHealth } from '../types'

type ConnectionState = 'checking' | 'connected' | 'offline'

interface ApiContextValue {
  connection: ConnectionState
  health: ApiHealth | null
  catalog: ApiCatalog | null
  experiments: ApiExperimentSummary[]
  error: string
  lastSyncedAt: Date | null
  refresh: () => Promise<void>
  refreshExperiments: () => Promise<void>
}

const ApiContext = createContext<ApiContextValue | null>(null)

export function ApiProvider({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()
  const [connection, setConnection] = useState<ConnectionState>('checking')
  const [health, setHealth] = useState<ApiHealth | null>(null)
  const [catalog, setCatalog] = useState<ApiCatalog | null>(null)
  const [experiments, setExperiments] = useState<ApiExperimentSummary[]>([])
  const [error, setError] = useState('')
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null)
  const pendingRefresh = useRef<Promise<void> | null>(null)

  const refresh = useCallback(() => {
    if (pendingRefresh.current) return pendingRefresh.current
    const pending = (async () => {
      try {
        const [nextHealth, nextCatalog, nextExperiments] = await Promise.all([
          getHealth(), getCatalog(), listExperiments(),
        ])
        setHealth(nextHealth)
        setCatalog(nextCatalog)
        setExperiments(nextExperiments)
        setLastSyncedAt(new Date())
        setError('')
        setConnection('connected')
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : '本地研究数据同步失败。')
        setConnection('offline')
      }
    })()
    pendingRefresh.current = pending
    void pending.finally(() => { pendingRefresh.current = null })
    return pending
  }, [])

  // Navigation in the SPA must also refresh the model/runtime catalog.
  useEffect(() => { void refresh() }, [pathname, refresh])

  useEffect(() => {
    const refreshVisible = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    window.addEventListener('focus', refreshVisible)
    document.addEventListener('visibilitychange', refreshVisible)
    const timer = window.setInterval(refreshVisible, 30_000)
    return () => {
      window.removeEventListener('focus', refreshVisible)
      document.removeEventListener('visibilitychange', refreshVisible)
      window.clearInterval(timer)
    }
  }, [refresh])

  const refreshExperiments = useCallback(async () => {
    // An older in-flight read may predate the experiment that just completed.
    if (pendingRefresh.current) await pendingRefresh.current
    await refresh()
  }, [refresh])

  const value = useMemo<ApiContextValue>(() => ({
    connection,
    health,
    catalog,
    experiments,
    error,
    lastSyncedAt,
    refresh,
    refreshExperiments,
  }), [connection, health, catalog, experiments, error, lastSyncedAt, refresh, refreshExperiments])

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>
}

export function useApi(): ApiContextValue {
  const value = useContext(ApiContext)
  if (!value) throw new Error('useApi must be used inside ApiProvider')
  return value
}
