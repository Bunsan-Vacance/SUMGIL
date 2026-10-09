import { useEffect, useRef, useState } from 'react'
import { congestionBatchRepository } from '../../api/congestion'
import type { CongestionBatchRepository } from '../../api/congestion'
import type { NearbyStation, StationRepository } from '../../api/contracts'
import { stationRepository } from '../../api/repositories'
import { segmentCongestionGradeForLevel } from '../route/segmentCongestion'
import type { SegmentCongestionGrade } from '../route/types'

export interface StationCongestion extends NearbyStation {
  level: number | null
  grade: SegmentCongestionGrade | null
  updatedAt: string | null
}

export type NearbyStationStatus = 'idle' | 'loading' | 'ready' | 'error'

const SEARCH_RADIUS_METERS = 1500
const SEARCH_LIMIT = 30

// 소수 3자리(약 100m)가 같으면 같은 위치로 보고 다시 조회하지 않는다.
const round3 = (value: number) => Math.round(value * 1000) / 1000
const centerKey = (center: { lat: number; lng: number }) =>
  `${round3(center.lat)}:${round3(center.lng)}`

function withoutCongestion(stations: NearbyStation[]): StationCongestion[] {
  return stations.map((station) => ({ ...station, level: null, grade: null, updatedAt: null }))
}

/**
 * 지도 중심 주변 역과 현재 시각 혼잡도를 함께 조회한다.
 * 혼잡도 조회가 없거나 실패하면 역은 등급 없음(회색)으로 두고, 역 조회 실패만 error로 알린다.
 * enabled가 꺼져도 마지막 목록은 유지하고, 같은 위치로 다시 켜지면 재조회하지 않는다.
 */
export function useNearbyStationCongestion(
  center: { lat: number; lng: number } | null,
  enabled: boolean,
  stationRepo: Pick<StationRepository, 'nearby'> | null = stationRepository,
  batchRepo: CongestionBatchRepository | null = congestionBatchRepository,
  debounceMs = 300,
): { stations: StationCongestion[]; status: NearbyStationStatus; retry(): void } {
  const [stations, setStations] = useState<StationCongestion[]>([])
  const [status, setStatus] = useState<NearbyStationStatus>('idle')
  const [attempt, setAttempt] = useState(0)
  const key = center ? centerKey(center) : null
  const centerRef = useRef(center)
  centerRef.current = center
  const repositoriesRef = useRef({ stationRepo, batchRepo, debounceMs })
  repositoriesRef.current = { stationRepo, batchRepo, debounceMs }
  const requestId = useRef(0)
  const fetched = useRef<{ key: string; attempt: number } | null>(null)

  useEffect(() => {
    const target = centerRef.current
    const { stationRepo: nearbyRepo, batchRepo: batch, debounceMs: delay } = repositoriesRef.current
    if (!enabled || !key || !target || !nearbyRepo) return
    if (fetched.current?.key === key && fetched.current.attempt === attempt) return
    const controller = new AbortController()
    const id = ++requestId.current
    const current = () => !controller.signal.aborted && id === requestId.current
    const timer = setTimeout(() => {
      setStatus('loading')
      void (async () => {
        let nearby: NearbyStation[]
        try {
          nearby = await nearbyRepo.nearby(
            {
              lat: target.lat,
              lng: target.lng,
              radiusMeters: SEARCH_RADIUS_METERS,
              limit: SEARCH_LIMIT,
            },
            controller.signal,
          )
        } catch {
          if (current()) setStatus('error')
          return
        }
        if (!current()) return
        if (!nearby.length) {
          fetched.current = { key, attempt }
          setStations([])
          setStatus('ready')
          return
        }
        let merged = withoutCongestion(nearby)
        if (batch) {
          try {
            const result = await batch.batch(
              { targetType: 'STATION', targetIds: nearby.map((station) => station.stationId) },
              controller.signal,
            )
            const byId = new Map(result.targets.map((item) => [item.targetId, item]))
            merged = nearby.map((station) => {
              const slot = byId.get(station.stationId)?.slots[0]
              const level = slot?.level ?? null
              return {
                ...station,
                level,
                grade: segmentCongestionGradeForLevel(level ?? undefined) ?? null,
                updatedAt: slot?.updatedAt ?? null,
              }
            })
          } catch {
            // 혼잡도 조회 실패는 조용히 등급 없음으로 둔다.
          }
        }
        if (!current()) return
        fetched.current = { key, attempt }
        setStations(merged)
        setStatus('ready')
      })()
    }, delay)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [key, enabled, attempt])

  const retry = () => setAttempt((value) => value + 1)
  return { stations, status, retry }
}
