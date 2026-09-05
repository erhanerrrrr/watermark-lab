import { useCallback, useEffect, useState } from 'react'
import { getGeometryEvidence } from './api'
import type { GeometryEvidence } from '../types'

export function useGeometryEvidence() {
  const [evidence, setEvidence] = useState<GeometryEvidence | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const reload = useCallback(() => setRevision((value) => value + 1), [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    getGeometryEvidence()
      .then((result) => { if (active) setEvidence(result) })
      .catch((caught) => {
        if (active) {
          setEvidence(null)
          setError(caught instanceof Error ? caught.message : '独立验证证据读取失败。')
        }
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [revision])

  return { evidence, error, loading, reload }
}
