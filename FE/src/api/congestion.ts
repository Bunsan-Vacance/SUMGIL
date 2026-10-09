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

export interface CongestionBatchSlot {
  departureTime: string
  dowType: number
  timeSlot: number
  level: number | null
  source: string | null
  updatedAt: string | null
}

export interface CongestionBatchTarget {
  targetId: string
  slots: CongestionBatchSlot[]
}

export interface CongestionBatch {
  targetType: CongestionTarget
  departureTimes: string[]
  targets: CongestionBatchTarget[]
}

export interface CongestionBatchRequest {
  targetType: CongestionTarget
  targetIds: string[]
  /** ISO 시각(offset 포함 가능). 생략하면 서버 현재 시각 1개를 쓴다. */
  departureTimes?: string[]
}

export interface CongestionBatchRepository {
  batch(request: CongestionBatchRequest, signal: AbortSignal): Promise<CongestionBatch>
}

// BE 상한(CongestionQueryService)과 같은 값. 서버에 보내기 전에 막는다.
export const CONGESTION_BATCH_MAX_TARGETS = 50
export const CONGESTION_BATCH_MAX_TIMES = 12
export const CONGESTION_BATCH_MAX_COMBINATIONS = 200

function unique(values: string[]) {
  return [...new Set(values)]
}

function nullableText(value: unknown) {
  if (value === null) return null
  return typeof value === 'string' ? value : undefined
}

function mapBatchSlot(value: unknown): CongestionBatchSlot {
  const invalid = () =>
    new RepositoryError('invalid-response', '혼잡도 일괄 응답이 올바르지 않아요.')
  if (
    !isRecord(value) ||
    typeof value.departureTime !== 'string' ||
    !Number.isInteger(value.dowType) ||
    !number(value.dowType, 0, 2) ||
    !Number.isInteger(value.timeSlot) ||
    !number(value.timeSlot, 0, 47)
  ) {
    throw invalid()
  }
  // level은 null이면 "데이터 없음"이다. 0으로 바꾸지 않는다.
  if (value.level !== null && !number(value.level, 0, Number.MAX_SAFE_INTEGER)) throw invalid()
  const source = nullableText(value.source)
  const updatedAt = nullableText(value.updatedAt)
  if (source === undefined || updatedAt === undefined) throw invalid()
  return {
    departureTime: value.departureTime,
    dowType: value.dowType as number,
    timeSlot: value.timeSlot as number,
    level: value.level as number | null,
    source,
    updatedAt,
  }
}

function mapCongestionBatch(
  value: unknown,
  request: { targetType: CongestionTarget; targetIds: string[] },
): CongestionBatch {
  const invalid = () =>
    new RepositoryError('invalid-response', '혼잡도 일괄 응답이 올바르지 않아요.')
  if (
    !isRecord(value) ||
    value.targetType !== request.targetType ||
    !Array.isArray(value.departureTimes) ||
    !value.departureTimes.every((time) => typeof time === 'string') ||
    !Array.isArray(value.targets)
  ) {
    throw invalid()
  }
  const departureTimes = value.departureTimes as string[]
  const mismatch = () =>
    new RepositoryError('invalid-response', '혼잡도 일괄 응답이 요청과 달라요.')
  if (value.targets.length !== request.targetIds.length) throw mismatch()
  const targets = value.targets.map((item, index): CongestionBatchTarget => {
    if (!isRecord(item) || !text(item.targetId) || !Array.isArray(item.slots)) throw invalid()
    if (text(item.targetId) !== request.targetIds[index]) throw mismatch()
    if (item.slots.length !== departureTimes.length) throw mismatch()
    return { targetId: text(item.targetId) as string, slots: item.slots.map(mapBatchSlot) }
  })
  return { targetType: request.targetType, departureTimes, targets }
}

export function createBackendCongestionBatchRepository(baseUrl: string): CongestionBatchRepository {
  return {
    async batch(request, signal) {
      const targetIds = unique(request.targetIds.map((id) => id.trim()).filter(Boolean))
      if (!targetIds.length) throw new RepositoryError('bad-request', '혼잡도 대상이 없어요.')
      let times: string[] | undefined
      if (request.departureTimes?.length) {
        times = []
        for (const time of request.departureTimes) {
          const converted = backendDepartureTime(time)
          if (!converted) throw new RepositoryError('bad-request', '출발 시각을 확인해 주세요.')
          times.push(converted)
        }
        times = unique(times)
      }
      const timeCount = times?.length ?? 1
      if (
        targetIds.length > CONGESTION_BATCH_MAX_TARGETS ||
        timeCount > CONGESTION_BATCH_MAX_TIMES ||
        targetIds.length * timeCount > CONGESTION_BATCH_MAX_COMBINATIONS
      ) {
        throw new RepositoryError('bad-request', '한 번에 조회할 수 있는 수를 넘었어요.')
      }
      const params = new URLSearchParams({
        targetType: request.targetType,
        targetIds: targetIds.join(','),
      })
      if (times) params.set('departureTimes', times.join(','))
      const data = await requestApi<unknown>(
        `${baseUrl}/api/congestion/batch?${params.toString()}`,
        signal,
      )
      return mapCongestionBatch(data, { targetType: request.targetType, targetIds })
    },
  }
}

export const congestionBatchRepository: CongestionBatchRepository | null = apiBaseUrl
  ? createBackendCongestionBatchRepository(apiBaseUrl)
  : null
