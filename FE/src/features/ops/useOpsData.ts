import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { OpsRepository } from '../../api/contracts'
import { RepositoryError } from '../../api/errors'
import { segmentCongestionGradeForLevel } from '../route/segmentCongestion'
import type { SegmentCongestionGrade } from '../route/types'
import type {
  BikeStockOverview,
  CongestionHeatmap,
  LatLng,
  OpsDataSource,
  OpsResult,
} from './types'

export const OPS_POLL_MS = 60_000
// 서울 전역 조회 범위(운영자 뷰 기본값). 지도 레이어가 붙으면 화면 bbox로 대체한다.
export const SEOUL_BOUNDS: { sw: LatLng; ne: LatLng } = {
  sw: { lat: 37.42, lng: 126.76 },
  ne: { lat: 37.72, lng: 127.19 },
}
export const OPS_STOCK_LIMIT = 200

export type OpsStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error'
export interface OpsDatasetState<T> {
  status: OpsStatus
  data?: T
  /** status가 error면 데이터 없이 실패한 것. ready·empty와 함께 있으면 재조회가 실패했지만 이전 data를 유지 중이다. */
  error?: string
  source?: OpsDataSource
  /** 이전 data를 유지한 채 재조회(bbox·날짜 변경, 수동 새로고침) 중이다. 폴링은 표시하지 않는다. */
  refreshing?: boolean
}

const idle = { status: 'idle' } as const

function errorMessage(error: unknown) {
  return error instanceof RepositoryError ? error.message : '데이터를 불러오지 못했어요.'
}

/**
 * 한 데이터셋의 조회 상태 머신. load는 참조가 안정적이어야 한다(useCallback).
 * 이전 data가 있으면 재조회 중에도 data·source를 유지하고 refreshing만 켠다(첫 조회만 loading).
 * 재조회가 실패해도 data를 유지하고 error를 함께 둔다.
 * 탭이 보일 때만 pollMs마다 다시 조회하고, 요청마다 AbortController를 쓰며,
 * 취소·교체된 요청의 늦은 응답은 상태에 반영하지 않는다.
 */
function useDataset<T>(
  load: (signal: AbortSignal) => Promise<OpsResult<T>>,
  isEmpty: (data: T) => boolean,
  pollMs: number,
) {
  const [state, setState] = useState<OpsDatasetState<T>>(idle)
  const controller = useRef<AbortController | null>(null)
  const lastStarted = useRef(0)
  const isEmptyRef = useRef(isEmpty)
  useEffect(() => {
    isEmptyRef.current = isEmpty
  }, [isEmpty])

  const run = useCallback(
    (initial: boolean) => {
      controller.current?.abort()
      const own = new AbortController()
      controller.current = own
      lastStarted.current = Date.now()
      // 데이터가 없을 때만 전체 로딩. 있으면 유지하고 refreshing만 켠다. 폴링은 아무것도 바꾸지 않는다.
      if (initial) {
        setState((prev) =>
          prev.data === undefined
            ? { status: 'loading' }
            : { ...prev, refreshing: true, error: undefined },
        )
      }
      load(own.signal).then(
        (result) => {
          if (own.signal.aborted || controller.current !== own) return
          setState({
            status: isEmptyRef.current(result.data) ? 'empty' : 'ready',
            data: result.data,
            source: result.source,
          })
        },
        (error: unknown) => {
          if (own.signal.aborted || controller.current !== own) return
          const message = errorMessage(error)
          setState((prev) =>
            prev.data === undefined
              ? { status: 'error', error: message }
              : { ...prev, refreshing: false, error: message },
          )
        },
      )
    },
    [load],
  )

  useEffect(() => {
    run(true)
    const tick = () => {
      if (document.visibilityState === 'visible') run(false)
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible' && Date.now() - lastStarted.current >= pollMs) {
        run(false)
      }
    }
    const timer = setInterval(tick, pollMs)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      controller.current?.abort()
      controller.current = null
    }
  }, [run, pollMs])

  const refresh = useCallback(() => run(true), [run])
  return { state, refresh }
}

export interface UseOpsDataOptions {
  /** null이면 조회하지 않고 오류 상태가 된다. 실패를 mock으로 대체하지 않는다. */
  repository: OpsRepository | null
  bounds?: { sw: LatLng; ne: LatLng }
  arrivalTime?: string
  date?: string
  pollMs?: number
}

const unconfigured = () =>
  Promise.reject(new RepositoryError('network', '운영 API 주소가 설정되지 않았어요.'))

export function useOpsData({
  repository,
  bounds = SEOUL_BOUNDS,
  arrivalTime,
  date,
  pollMs = OPS_POLL_MS,
}: UseOpsDataOptions) {
  const { lat: swLat, lng: swLng } = bounds.sw
  const { lat: neLat, lng: neLng } = bounds.ne
  const loadStock = useCallback(
    (signal: AbortSignal) =>
      repository
        ? repository.bikeStockOverview(
            {
              sw: { lat: swLat, lng: swLng },
              ne: { lat: neLat, lng: neLng },
              arrivalTime,
              limit: OPS_STOCK_LIMIT,
            },
            signal,
          )
        : unconfigured(),
    [repository, swLat, swLng, neLat, neLng, arrivalTime],
  )
  const loadHeatmap = useCallback(
    (signal: AbortSignal) =>
      repository ? repository.congestionHeatmap({ date }, signal) : unconfigured(),
    [repository, date],
  )
  const stockEmpty = useCallback((data: BikeStockOverview) => data.items.length === 0, [])
  const heatmapEmpty = useCallback((data: CongestionHeatmap) => data.lines.length === 0, [])
  const stock = useDataset(loadStock, stockEmpty, pollMs)
  const heatmap = useDataset(loadHeatmap, heatmapEmpty, pollMs)
  return useMemo(
    () => ({
      stock: stock.state,
      heatmap: heatmap.state,
      refreshStock: stock.refresh,
      refreshHeatmap: heatmap.refresh,
    }),
    [stock.state, heatmap.state, stock.refresh, heatmap.refresh],
  )
}

export type StockLevel = 'low' | 'mid' | 'good' | 'unknown'

/** 운영자 뷰 전용 재고 구간(확정 규칙). 재고가 이 값 이하면 부족, STOCK_GOOD_MIN 이상이면 여유다. */
export const STOCK_LOW_MAX = 2
export const STOCK_GOOD_MIN = 5

/** 현재 재고가 null이면 예측값을 쓰고, 둘 다 null이면 알 수 없음이다. */
export function stockLevel(
  availableBikes: number | null,
  predictedBikes: number | null,
): StockLevel {
  const value = availableBikes ?? predictedBikes
  if (value === null) return 'unknown'
  if (value <= STOCK_LOW_MAX) return 'low'
  if (value >= STOCK_GOOD_MIN) return 'good'
  return 'mid'
}

/** 'none'은 데이터 없음, 그 외는 사용자 지도와 같은 구간 등급이다. */
export type HeatmapTone = SegmentCongestionGrade | 'none'

/**
 * 혼잡도 level을 사용자 화면과 같은 4단계 등급(40/70/100, `segmentCongestionGradeForLevel`)으로 나눈다.
 * null·비정상 값은 'none'(데이터 없음)이다.
 */
export function heatmapCellTone(level: number | null): HeatmapTone {
  if (level === null) return 'none'
  return segmentCongestionGradeForLevel(level) ?? 'none'
}
