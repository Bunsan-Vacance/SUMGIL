import { useEffect, useRef, useState } from 'react'
import { guidanceRepository } from '../../api/guidance'
import type { GuidanceRepository, TrainArrivalResult } from '../../api/guidance'
import { groupArrivalsByDirection } from './stationArrivals'
import type { DirectionArrivals } from './stationArrivals'

export type ArrivalsStatus = 'loading' | 'success' | 'error' | 'unsupported'

/**
 * 역 하나·노선 하나의 실시간 도착 정보를 조회하고 열려 있는 동안 주기적으로 갱신한다.
 * 갱신은 탭이 보일 때만 하고, 갱신 중에는 기존 결과를 유지해 깜빡임을 막는다.
 */
export function useStationArrivals(
  stationId: string,
  lineId: string | null,
  stationName: string,
  lineName: string | null,
  repository: Pick<GuidanceRepository, 'arrivals'> | null = guidanceRepository,
  refreshMs = 30_000,
  now: () => Date = () => new Date(),
): {
  status: ArrivalsStatus
  result: TrainArrivalResult | null
  fetchedAt: string | null
  directions: DirectionArrivals[]
  retry(): void
} {
  const supported = Boolean(lineId && repository)
  const [status, setStatus] = useState<ArrivalsStatus>(supported ? 'loading' : 'unsupported')
  const [result, setResult] = useState<TrainArrivalResult | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)
  const [directions, setDirections] = useState<DirectionArrivals[]>([])
  const [attempt, setAttempt] = useState(0)
  const optionsRef = useRef({ repository, refreshMs, now, stationName, lineName })
  optionsRef.current = { repository, refreshMs, now, stationName, lineName }
  const requestId = useRef(0)
  const lastKey = useRef<string | null>(null)

  useEffect(() => {
    const repo = optionsRef.current.repository
    if (!lineId || !repo) {
      lastKey.current = null
      setResult(null)
      setFetchedAt(null)
      setDirections([])
      setStatus('unsupported')
      return
    }
    const key = `${stationId}:${lineId}`
    if (lastKey.current !== key) {
      setResult(null)
      setFetchedAt(null)
      setDirections([])
    }
    lastKey.current = key
    setStatus('loading')
    let controller: AbortController | null = null
    const load = () => {
      controller?.abort()
      const own = new AbortController()
      controller = own
      const id = ++requestId.current
      const current = () => !own.signal.aborted && id === requestId.current
      const { stationName: name, lineName: line } = optionsRef.current
      repo
        .arrivals(
          { stationId, routeId: lineId, stationName: name, routeName: line ?? undefined },
          own.signal,
        )
        .then((value) => {
          if (!current()) return
          const at = optionsRef.current.now()
          setResult(value)
          setFetchedAt(at.toISOString())
          setDirections(groupArrivalsByDirection(value.trains, at))
          setStatus('success')
        })
        .catch((error: unknown) => {
          if (!current()) return
          if (error instanceof DOMException && error.name === 'AbortError') return
          setStatus('error')
        })
    }
    load()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, optionsRef.current.refreshMs)
    return () => {
      clearInterval(timer)
      controller?.abort()
    }
  }, [stationId, lineId, attempt])

  const retry = () => setAttempt((value) => value + 1)
  return { status, result, fetchedAt, directions, retry }
}
