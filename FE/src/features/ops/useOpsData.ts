import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { OpsRepository } from '../../api/contracts'
import { RepositoryError } from '../../api/errors'
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
  error?: string
  source?: OpsDataSource
}

const idle = { status: 'idle' } as const

function errorMessage(error: unknown) {
  return error instanceof RepositoryError ? error.message : '데이터를 불러오지 못했어요.'
}

/**
 * 한 데이터셋의 조회 상태 머신. load는 참조가 안정적이어야 한다(useCallback).
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
      // 첫 조회·재시도만 로딩 표시. 폴링 중에는 이전 결과를 그대로 보여준다.
      if (initial) setState({ status: 'loading' })
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
          setState({ status: 'error', error: errorMessage(error) })
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

/** 부족 ≤2, 여유 ≥5(제안 임계, 확정 전). 현재 재고가 null이면 예측값을 쓰고, 둘 다 null이면 알 수 없음이다. */
export function stockLevel(
  availableBikes: number | null,
  predictedBikes: number | null,
): StockLevel {
  const value = availableBikes ?? predictedBikes
  if (value === null) return 'unknown'
  if (value <= 2) return 'low'
  if (value >= 5) return 'good'
  return 'mid'
}

export type HeatmapTone = 'none' | 'tone-1' | 'tone-2' | 'tone-3' | 'tone-4' | 'tone-5'

/**
 * 혼잡도 level 구간 버킷. 임계 0/60/90/120/150은 잠정값이며 AI 혼잡 등급표와 맞춰 확정한다.
 * null·비정상 값은 'none'(데이터 없음)이다.
 */
export function heatmapCellTone(level: number | null): HeatmapTone {
  if (level === null || !Number.isFinite(level)) return 'none'
  if (level < 60) return 'tone-1'
  if (level < 90) return 'tone-2'
  if (level < 120) return 'tone-3'
  if (level < 150) return 'tone-4'
  return 'tone-5'
}
