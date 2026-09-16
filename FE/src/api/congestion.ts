import { RepositoryError } from './errors'
import { apiBaseUrl, backendDepartureTime, requestApi } from './repositories'

export type CongestionTarget = 'STATION' | 'LINE' | 'ROUTE'

export interface Congestion {
  targetType: CongestionTarget
  targetId: string
  dowType: number
  timeSlot: number
  level: number
  source: string
  updatedAt: string
}

export interface CongestionRepository {
  get(
    targetType: CongestionTarget,
    targetId: string,
    departureTime: string | undefined,
    signal: AbortSignal,
  ): Promise<Congestion | undefined>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function text(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function number(value: unknown, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}

function targetType(value: unknown): CongestionTarget | undefined {
  return value === 'STATION' || value === 'LINE' || value === 'ROUTE' ? value : undefined
}

function mapCongestion(value: unknown): Congestion | undefined {
  if (value === undefined || value === null) return undefined
  if (
    !isRecord(value) ||
    !targetType(value.targetType) ||
    !text(value.targetId) ||
    !number(value.dowType, 0, 6) ||
    !Number.isInteger(value.dowType) ||
    !number(value.timeSlot, 0, 47) ||
    !Number.isInteger(value.timeSlot) ||
    !number(value.level, 0, Number.MAX_SAFE_INTEGER) ||
    !text(value.source) ||
    !text(value.updatedAt)
  ) {
    throw new RepositoryError('invalid-response', '혼잡도 응답이 올바르지 않아요.')
  }
  return {
    targetType: targetType(value.targetType) as CongestionTarget,
    targetId: text(value.targetId) as string,
    dowType: value.dowType as number,
    timeSlot: value.timeSlot as number,
    level: value.level as number,
    source: text(value.source) as string,
    updatedAt: text(value.updatedAt) as string,
  }
}

export function createBackendCongestionRepository(baseUrl: string): CongestionRepository {
  return {
    async get(target, targetId, departureTime, signal) {
      const id = targetId.trim()
      if (!id) throw new RepositoryError('invalid-response', '혼잡도 대상이 올바르지 않아요.')
      const params = new URLSearchParams({ targetType: target, targetId: id })
      const localTime = departureTime ? backendDepartureTime(departureTime) : undefined
      if (localTime) params.set('departureTime', localTime)
      const data = await requestApi<unknown>(
        `${baseUrl}/api/congestion?${params.toString()}`,
        signal,
        {},
        true,
      )
      const result = mapCongestion(data)
      if (result && (result.targetType !== target || result.targetId !== id)) {
        throw new RepositoryError('invalid-response', '혼잡도 대상이 요청과 다릅니다.')
      }
      return result
    },
  }
}

export const congestionRepository = apiBaseUrl
  ? createBackendCongestionRepository(apiBaseUrl)
  : null
