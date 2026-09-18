import { mapBackendRoute } from './routeMapper'
import { RepositoryError } from './errors'
import { requestApi, apiBaseUrl } from './repositories'
import type { Mode, Place, Route, RouteEndpoint } from '../features/route/types'

export type GuidanceSource = 'ALGORITHM' | 'MOCK'

export interface TrainArrival {
  trainId: string
  direction: string
  arrivalTime: string
  updatedAt: string
  source: 'LIVE' | 'MOCK'
}

export type TrainArrivalDataStatus = 'LIVE' | 'NO_INFO' | 'OUTSIDE_WINDOW' | 'STALE'

export interface TrainArrivalResult {
  status: TrainArrivalDataStatus
  trains: TrainArrival[]
  updatedAt: string | null
}

export interface TrainArrivalRequest {
  stationId: string
  routeId: string
  stationName?: string
  routeName?: string
}

export interface GuidanceConditions {
  modes: Mode[]
  priority: 'fast' | 'calm'
  departedAt?: string
  requestedAt?: string
}

export interface ReplanRequest {
  currentRoute: Route
  step: number
  currentBoundary: RouteEndpoint
  currentLeg: Pick<Route['legs'][number], 'mode' | 'routeId' | 'from' | 'to'>
  destination: Place
  conditions: GuidanceConditions
}

export interface ReplanProposal {
  route: Route
  reason: string
  source: GuidanceSource
}

export interface GuidanceRepository {
  arrivals(request: TrainArrivalRequest, signal: AbortSignal): Promise<TrainArrivalResult>
  replan(request: ReplanRequest, signal: AbortSignal): Promise<ReplanProposal[]>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function text(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function timestamp(value: unknown) {
  const parsed = text(value)
  if (
    !parsed ||
    !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(parsed) ||
    !Number.isFinite(new Date(parsed).getTime())
  ) {
    throw new RepositoryError('invalid-response', '실시간 도착 정보 응답이 올바르지 않아요.')
  }
  return parsed
}

function mapArrival(value: unknown): TrainArrival {
  if (!isRecord(value)) {
    throw new RepositoryError('invalid-response', '실시간 도착 정보 응답이 올바르지 않아요.')
  }
  const trainId = text(value.trainId)
  const direction = text(value.direction)
  if (!trainId || !direction || (value.source !== 'LIVE' && value.source !== 'MOCK')) {
    throw new RepositoryError('invalid-response', '실시간 도착 정보 응답이 올바르지 않아요.')
  }
  return {
    trainId,
    direction,
    arrivalTime: timestamp(value.arrivalTime),
    updatedAt: timestamp(value.updatedAt),
    source: value.source,
  }
}

function mapArrivalResult(value: unknown): TrainArrivalResult {
  if (!isRecord(value)) {
    throw new RepositoryError('invalid-response', '실시간 도착 정보 응답이 올바르지 않아요.')
  }
  const statuses: TrainArrivalDataStatus[] = ['LIVE', 'NO_INFO', 'OUTSIDE_WINDOW', 'STALE']
  if (!statuses.includes(value.status as TrainArrivalDataStatus) || !Array.isArray(value.trains)) {
    throw new RepositoryError('invalid-response', '실시간 도착 정보 응답이 올바르지 않아요.')
  }
  const status = value.status as TrainArrivalDataStatus
  const trains = value.trains.map(mapArrival)
  if ((status === 'LIVE') !== trains.length > 0) {
    throw new RepositoryError(
      'invalid-response',
      '실시간 도착 정보 상태와 열차 목록이 맞지 않아요.',
    )
  }
  return {
    status,
    trains,
    updatedAt: value.updatedAt == null ? null : timestamp(value.updatedAt),
  }
}

function endpointMatches(actual: RouteEndpoint | undefined, expected: RouteEndpoint) {
  if (!actual) return false
  if (expected.id) return Boolean(actual.id && expected.id === actual.id)
  return (
    expected.lat !== undefined &&
    expected.lng !== undefined &&
    actual.lat !== undefined &&
    actual.lng !== undefined &&
    Math.abs(expected.lat - actual.lat) < 0.00001 &&
    Math.abs(expected.lng - actual.lng) < 0.00001
  )
}

function mapProposal(
  value: unknown,
  index: number,
  departedAt: string,
  request: ReplanRequest,
): ReplanProposal {
  if (!isRecord(value) || !text(value.reason)) {
    throw new RepositoryError('invalid-response', '재탐색 응답이 올바르지 않아요.')
  }
  if (value.source !== 'ALGORITHM' && value.source !== 'MOCK') {
    throw new RepositoryError('invalid-response', '재탐색 응답이 올바르지 않아요.')
  }
  const route = mapBackendRoute(value.route, index, departedAt)
  const legMinutes = route.legs.reduce((total, leg) => total + leg.minutes, 0)
  if (Math.abs(route.minutes - legMinutes) > 0.01) {
    throw new RepositoryError('invalid-response', '재탐색 시간과 잔여 구간 시간이 다릅니다.')
  }
  if (
    !endpointMatches(route.legs[0]?.from, request.currentBoundary) ||
    !endpointMatches(route.legs.at(-1)?.to, {
      ...(request.destination.stationId ? { id: request.destination.stationId } : {}),
      ...(request.destination.lat !== undefined ? { lat: request.destination.lat } : {}),
      ...(request.destination.lng !== undefined ? { lng: request.destination.lng } : {}),
    })
  ) {
    throw new RepositoryError(
      'invalid-response',
      '재탐색 경계 또는 목적지 응답이 현재 안내와 다릅니다.',
    )
  }
  return { route, reason: value.reason as string, source: value.source }
}

export function createBackendGuidanceRepository(baseUrl: string): GuidanceRepository {
  return {
    async arrivals(request, signal) {
      const stationId = request.stationId.trim()
      const routeId = request.routeId.trim()
      if (!stationId || !routeId) {
        throw new RepositoryError('bad-request', '탑승 구간 정보를 확인해 주세요.')
      }
      const params = new URLSearchParams({ stationId, routeId })
      const data = await requestApi<unknown>(
        `${baseUrl}/api/transit/arrivals?${params.toString()}`,
        signal,
      )
      return mapArrivalResult(data)
    },
    async replan(request, signal) {
      const boundaryId = request.currentBoundary.id?.trim()
      const destStationId = request.destination.stationId?.trim()
      const hasDestinationCoordinates =
        Number.isFinite(request.destination.lat) && Number.isFinite(request.destination.lng)
      if (
        !request.currentRoute.id ||
        !Number.isInteger(request.step) ||
        request.step < 0 ||
        !boundaryId ||
        (!destStationId && !hasDestinationCoordinates)
      ) {
        throw new RepositoryError('bad-request', '현재 안내 정보를 확인해 주세요.')
      }
      const departedAt = request.conditions.requestedAt || new Date().toISOString()
      const data = await requestApi<unknown>(`${baseUrl}/api/routes/replan`, signal, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          step: request.step,
          boundaryId,
          destStationId: destStationId || null,
          destLat: request.destination.lat ?? null,
          destLng: request.destination.lng ?? null,
          modes: request.conditions.modes,
          priority: request.conditions.priority,
          requestedAt: departedAt,
        }),
      })
      if (!Array.isArray(data)) {
        throw new RepositoryError('invalid-response', '재탐색 응답이 올바르지 않아요.')
      }
      return data.map((proposal, index) => mapProposal(proposal, index, departedAt, request))
    },
  }
}

function mockArrivalTime(offsetMinutes: number) {
  return new Date(Date.now() + offsetMinutes * 60_000).toISOString()
}

export const mockGuidanceRepository: GuidanceRepository = {
  async arrivals(request, signal) {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, 120)
      signal.addEventListener(
        'abort',
        () => {
          clearTimeout(timer)
          reject(new DOMException('Aborted', 'AbortError'))
        },
        { once: true },
      )
    })
    const updatedAt = new Date().toISOString()
    return {
      status: 'LIVE',
      trains: [2, 5].map((offset, index) => ({
        trainId: `${request.routeId}-${index + 1}`,
        direction: `${request.routeName || request.stationName || request.routeId} 방면`,
        arrivalTime: mockArrivalTime(offset),
        updatedAt,
        source: 'MOCK' as const,
      })),
      updatedAt,
    }
  },
  async replan(request, signal) {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, 160)
      signal.addEventListener(
        'abort',
        () => {
          clearTimeout(timer)
          reject(new DOMException('Aborted', 'AbortError'))
        },
        { once: true },
      )
    })
    const remaining = request.currentRoute.legs.slice(request.step)
    if (!remaining.length) return []
    const baseMinutes = remaining.reduce((sum, leg) => sum + leg.minutes, 0)
    const destinationEndpoint = {
      id: request.destination.stationId || request.destination.id,
      name: request.destination.name,
      lat: request.destination.lat,
      lng: request.destination.lng,
    }
    const replannedLegs = [
      {
        ...remaining[0],
        title: `${request.currentBoundary.name || remaining[0].title}에서 다시 이동`,
        minutes: remaining[0].minutes + 4,
        from: request.currentBoundary,
      },
      ...remaining.slice(1),
    ]
    replannedLegs[replannedLegs.length - 1] = {
      ...replannedLegs.at(-1)!,
      to: destinationEndpoint,
    }
    const route = {
      ...request.currentRoute,
      id: `${request.currentRoute.id}-replan`,
      label: '현재 위치부터 다시 찾은 경로',
      minutes: baseMinutes + 4,
      departedAt: request.conditions.requestedAt || new Date().toISOString(),
      legs: replannedLegs,
    }
    return [
      {
        route,
        reason: `${request.currentBoundary.name || '현재 위치'}에서 ${request.destination.name}까지 남은 구간을 다시 계산했어요.`,
        source: 'MOCK' as const,
      },
    ]
  },
}

export const isGuidanceMockEnabled =
  import.meta.env.VITE_GUIDANCE_MOCK?.trim().toLowerCase() === 'true' || !apiBaseUrl

export const guidanceRepository: GuidanceRepository = isGuidanceMockEnabled
  ? mockGuidanceRepository
  : createBackendGuidanceRepository(apiBaseUrl!)
