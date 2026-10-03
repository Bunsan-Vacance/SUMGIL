import { requestApi } from './repositories'
import { RepositoryError } from './errors'
import type { OpsRepository } from './contracts'
import type {
  BikeStockOverview,
  BikeStockOverviewItem,
  CongestionHeatmap,
  HeatmapCell,
  HeatmapLine,
  PredictionSource,
  PredictionStatus,
  StockStatus,
} from '../features/ops/types'

// BE 계약 제안(TO_BE-ops-visualization-01) 기준 응답 검증·변환, 확정 전.
// 개별 행이 잘못되면 그 행만 버리고, 바깥 구조가 잘못되면 오류로 던진다. 값은 지어내지 않는다.

const abortError = () => new DOMException('Aborted', 'AbortError')
const invalid = (message: string) => new RepositoryError('invalid-response', message)

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
function text(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}
function finite(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}
/** null·undefined는 null로, 유효한 숫자는 그대로, 그 밖은 undefined(= 행 무효)로 돌려준다. */
function nullableNumber(value: unknown, min: number, max: number) {
  if (value === null || value === undefined) return null
  return finite(value, min, max) ? value : undefined
}
function nullableText(value: unknown) {
  if (value === null || value === undefined) return null
  return text(value) ?? undefined
}

const stockStatuses: readonly unknown[] = ['AVAILABLE', 'STALE', 'UNAVAILABLE']
const predictionStatuses: readonly unknown[] = ['AVAILABLE', 'UNAVAILABLE']
const predictionSources: readonly unknown[] = ['TABLE', 'MODEL', 'MOCK']
const MAX = Number.MAX_SAFE_INTEGER

function mapItem(value: unknown): BikeStockOverviewItem | null {
  if (!isRecord(value)) return null
  const rentalId = text(value.rentalId)
  const name = text(value.name)
  if (!rentalId || !name || !finite(value.lat, -90, 90) || !finite(value.lng, -180, 180)) {
    return null
  }
  if (!stockStatuses.includes(value.stockStatus)) return null
  if (!predictionStatuses.includes(value.predictionStatus)) return null
  const rackCount = nullableNumber(value.rackCount, 0, MAX)
  const availableBikes = nullableNumber(value.availableBikes, 0, MAX)
  const predictedBikes = nullableNumber(value.predictedBikes, 0, MAX)
  const probability = nullableNumber(value.availabilityProbability, 0, 1)
  const stockUpdatedAt = nullableText(value.stockUpdatedAt)
  const predictedAt = nullableText(value.predictedAt)
  if (
    rackCount === undefined ||
    availableBikes === undefined ||
    predictedBikes === undefined ||
    probability === undefined ||
    stockUpdatedAt === undefined ||
    predictedAt === undefined
  ) {
    return null
  }
  return {
    rentalId,
    name,
    lat: value.lat,
    lng: value.lng,
    rackCount,
    availableBikes,
    stockStatus: value.stockStatus as StockStatus,
    stockUpdatedAt,
    predictedBikes,
    availabilityProbability: probability,
    predictionStatus: value.predictionStatus as PredictionStatus,
    predictionSource: predictionSources.includes(value.predictionSource)
      ? (value.predictionSource as PredictionSource)
      : null,
    predictedAt,
  }
}

export function mapBikeStockOverview(value: unknown): BikeStockOverview {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw invalid('대여소 재고 응답이 올바르지 않아요.')
  }
  const items = value.items
    .map(mapItem)
    .filter((item): item is BikeStockOverviewItem => item !== null)
  return {
    arrivalTime: text(value.arrivalTime) ?? null,
    count: finite(value.count, 0, MAX) ? value.count : items.length,
    truncated: value.truncated === true,
    generatedAt: text(value.generatedAt) ?? null,
    items,
  }
}

function mapCell(value: unknown): HeatmapCell | null {
  if (!isRecord(value) || !Number.isInteger(value.timeSlot) || !finite(value.timeSlot, 0, 47)) {
    return null
  }
  const level = nullableNumber(value.level, 0, MAX)
  const nLinks = nullableNumber(value.nLinks, 0, MAX)
  const nFallback = nullableNumber(value.nFallback, 0, MAX)
  const maxLevel = nullableNumber(value.maxLevel, 0, MAX)
  if (
    level === undefined ||
    nLinks === undefined ||
    nFallback === undefined ||
    maxLevel === undefined
  ) {
    return null
  }
  return { timeSlot: value.timeSlot, level, nLinks, nFallback, maxLevel }
}

function mapLine(value: unknown): HeatmapLine | null {
  if (!isRecord(value) || !Array.isArray(value.cells)) return null
  const lineId = text(value.lineId)
  if (!lineId) return null
  return {
    lineId,
    lineName: text(value.lineName) ?? lineId,
    cells: value.cells.map(mapCell).filter((cell): cell is HeatmapCell => cell !== null),
  }
}

export function mapCongestionHeatmap(value: unknown): CongestionHeatmap {
  if (!isRecord(value) || !Array.isArray(value.lines) || !text(value.date)) {
    throw invalid('혼잡도 히트맵 응답이 올바르지 않아요.')
  }
  return {
    date: text(value.date) as string,
    source: text(value.source) ?? 'congestion_pred',
    generatedAt: text(value.generatedAt) ?? null,
    predictorVersions: Array.isArray(value.predictorVersions)
      ? value.predictorVersions.map(text).filter((v): v is string => v !== undefined)
      : [],
    slotFrom: finite(value.slotFrom, 0, 47) ? value.slotFrom : 10,
    slotTo: finite(value.slotTo, 0, 47) ? value.slotTo : 47,
    lines: value.lines.map(mapLine).filter((line): line is HeatmapLine => line !== null),
  }
}

export function createBackendOpsRepository(baseUrl: string): OpsRepository {
  return {
    async bikeStockOverview(request, signal) {
      const { sw, ne } = request
      if (
        !finite(sw.lat, -90, 90) ||
        !finite(ne.lat, -90, 90) ||
        !finite(sw.lng, -180, 180) ||
        !finite(ne.lng, -180, 180) ||
        sw.lat > ne.lat ||
        sw.lng > ne.lng
      ) {
        throw new RepositoryError('bad-request', '조회 범위를 확인해 주세요.')
      }
      const params = new URLSearchParams({
        swLat: String(sw.lat),
        swLng: String(sw.lng),
        neLat: String(ne.lat),
        neLng: String(ne.lng),
      })
      if (request.arrivalTime) params.set('arrivalTime', request.arrivalTime)
      if (request.limit !== undefined) params.set('limit', String(request.limit))
      try {
        const data = await requestApi<unknown>(
          `${baseUrl}/api/ops/bike-stations/stock-overview?${params}`,
          signal,
        )
        return { source: 'api', data: mapBikeStockOverview(data) }
      } catch (error) {
        if (signal.aborted) throw abortError()
        throw error
      }
    },
    async congestionHeatmap(request, signal) {
      if (request.date !== undefined && !/^\d{4}-\d{2}-\d{2}$/.test(request.date)) {
        throw new RepositoryError('bad-request', '날짜 형식을 확인해 주세요.')
      }
      const query = request.date ? `?${new URLSearchParams({ date: request.date })}` : ''
      try {
        const data = await requestApi<unknown>(
          `${baseUrl}/api/ops/congestion/heatmap${query}`,
          signal,
        )
        return { source: 'api', data: mapCongestionHeatmap(data) }
      } catch (error) {
        if (signal.aborted) throw abortError()
        throw error
      }
    },
  }
}
