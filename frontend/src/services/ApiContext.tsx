import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { getCatalog, getHealth, listExperiments } from './api'
import type { ApiCatalog, ApiExperimentSummary, ApiHealth } from '../types'

type ConnectionState = 'checking' | 'connected' | 'offline'

interface ApiContextValue {
  connection: ConnectionState
  health: ApiHealth | null
  catalog: ApiCatalog | null
  experiments: ApiExperimentSummary[]
  error: string
  refresh: () => Promise<void>
  refreshExperiments: () => Promise<void>
}

const ApiContext = createContext<ApiContextValue | null>(null)

export function ApiProvider({ children }: { children: React.ReactNode }) {
  const [connection, setConnection] = useState<ConnectionState>('checking')
  const [health, setHealth] = useState<ApiHealth | null>(null)
  const [catalog, setCatalog] = useState<ApiCatalog | null>(null)
  const [experiments, setExperiments] = useState<ApiExperimentSummary[]>([])
  const [error, setError] = useState('')

  const refreshExperiments = useCallback(async () => {
    try {
      const [items, nextHealth] = await Promise.all([listExperiments(), getHealth()])
      setExperiments(items)
      setHealth(nextHealth)
      setError('')
      setConnection('connected')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '实验历史刷新失败。')
      setConnection('offline')
    }
  }, [])

  const refresh = useCallback(async () => {
    setConnection('checking')
    try {
      const [nextHealth, nextCatalog, nextExperiments] = await Promise.all([
        getHealth(),
        getCatalog(),
        listExperiments(),
      ])
      setHealth(nextHealth)
      setCatalog(nextCatalog)
      setExperiments(nextExperiments)
      setError('')
      setConnection('connected')
    } catch (caught) {
      setHealth(null)
      setCatalog(null)
      setExperiments([])
      setError(caught instanceof Error ? caught.message : '本地 API 初始化失败。')
      setConnection('offline')
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const value = useMemo<ApiContextValue>(() => ({
    connection,
    health,
    catalog,
    experiments,
    error,
    refresh,
    refreshExperiments,
  }), [connection, health, catalog, experiments, error, refresh, refreshExperiments])

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>
}

export function useApi(): ApiContextValue {
  const value = useContext(ApiContext)
  if (!value) throw new Error('useApi must be used inside ApiProvider')
  return value
}
