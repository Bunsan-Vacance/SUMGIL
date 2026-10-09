import { useEffect, useRef, useState } from 'react'
import { congestionBatchRepository } from '../../api/congestion'
import type { CongestionBatchRepository } from '../../api/congestion'
import { segmentCongestionGradeForLevel } from '../route/segmentCongestion'
import type { SegmentCongestionGrade } from '../route/types'

export interface HourlyBar {
  departureTime: string
  hour: number
  label: string
  level: number | null
  grade: SegmentCongestionGrade | null
}

// 현재 정시를 기준으로 한 시간 단위 오프셋. 지난 1시간부터 이후 4시간까지 6칸이다.
export const HOURLY_OFFSETS = [-1, 0, 1, 2, 3, 4] as const
export const HOURLY_NOW_INDEX = 1

const HOUR_MS = 3_600_000
const SEOUL_OFFSET_MS = 9 * HOUR_MS

function seoulFloorMs(now: Date) {
  return Math.floor((now.getTime() + SEOUL_OFFSET_MS) / HOUR_MS) * HOUR_MS - SEOUL_OFFSET_MS
}

/** now를 서울 기준 정시로 내린 뒤 오프셋별 ISO(UTC) 시각을 만든다. */
export function hourlyDepartureTimes(now: Date): string[] {
  const base = seoulFloorMs(now)
  return HOURLY_OFFSETS.map((offset) => new Date(base + offset * HOUR_MS).toISOString())
}

function seoulHour(iso: string) {
  return new Date(new Date(iso).getTime() + SEOUL_OFFSET_MS).getUTCHours()
}

export type HourlyStatus = 'loading' | 'success' | 'error' | 'unavailable'

/** 역 하나의 시간대별(지난 1시간~이후 4시간) 혼잡도를 일괄 조회로 한 번에 가져온다. */
export function useStationHourlyCongestion(
  stationId: string | null,
  repository: CongestionBatchRepository | null = congestionBatchRepository,
  now: () => Date = () => new Date(),
): { status: HourlyStatus; bars: HourlyBar[]; retry(): void } {
  const [status, setStatus] = useState<HourlyStatus>(
    stationId && repository ? 'loading' : 'unavailable',
  )
  const [bars, setBars] = useState<HourlyBar[]>([])
  const [attempt, setAttempt] = useState(0)
  const requestId = useRef(0)
  const repositoryRef = useRef(repository)
  repositoryRef.current = repository
  const nowRef = useRef(now)
  nowRef.current = now

  useEffect(() => {
    const id = ++requestId.current
    const repo = repositoryRef.current
    if (!stationId || !repo) {
      setBars([])
      setStatus('unavailable')
      return
    }
    const controller = new AbortController()
    const current = () => !controller.signal.aborted && id === requestId.current
    const times = hourlyDepartureTimes(nowRef.current())
    setBars([])
    setStatus('loading')
    repo
      .batch(
        { targetType: 'STATION', targetIds: [stationId], departureTimes: times },
        controller.signal,
      )
      .then((batch) => {
        if (!current()) return
        const slots = batch.targets[0]?.slots ?? []
        setBars(
          slots.map((slot, index) => {
            const level = slot.level ?? null
            return {
              departureTime: slot.departureTime,
              hour: seoulHour(times[index] ?? slot.departureTime),
              label: index === HOURLY_NOW_INDEX ? '지금' : `${seoulHour(times[index])}시`,
              level,
              grade: segmentCongestionGradeForLevel(level ?? undefined) ?? null,
            }
          }),
        )
        setStatus('success')
      })
      .catch((error: unknown) => {
        if (!current()) return
        if (error instanceof DOMException && error.name === 'AbortError') return
        setStatus('error')
      })
    return () => controller.abort()
  }, [stationId, attempt])

  const retry = () => setAttempt((value) => value + 1)
  return { status, bars, retry }
}
