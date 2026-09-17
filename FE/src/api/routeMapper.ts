import { RepositoryError } from './errors'
import type {
  GeometryLineString,
  Route,
  RouteEndpoint,
  RouteGeometry,
} from '../features/route/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function text(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function finite(value: unknown, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}

function parseGeometry(value: unknown, status: unknown): RouteGeometry | undefined {
  if (status !== undefined && status !== 'available' && status !== 'unavailable') {
    throw new RepositoryError('invalid-response', '지원하지 않는 경로 좌표 상태 응답이에요.')
  }
  if (status === 'unavailable' || value === null || value === undefined) return undefined
  if (!isRecord(value) || value.type !== 'MultiLineString' || !Array.isArray(value.coordinates)) {
    throw new RepositoryError('invalid-response', '경로 좌표 응답이 올바르지 않아요.')
  }
  const coordinates: GeometryLineString[] = value.coordinates.map((line) => {
    if (!Array.isArray(line) || line.length < 2) {
      throw new RepositoryError('invalid-response', '경로 좌표 응답이 올바르지 않아요.')
    }
    return line.map((point) => {
      if (
        !Array.isArray(point) ||
        point.length < 2 ||
        !finite(point[0], -180, 180) ||
        !finite(point[1], -90, 90)
      ) {
        throw new RepositoryError('invalid-response', '경로 좌표 응답이 올바르지 않아요.')
      }
      return [point[0], point[1]] as [number, number]
    })
  })
  return { type: 'MultiLineString', coordinates }
}

function mapMode(mode: unknown): { mode: 'walk' | 'subway' | 'bus' | 'bike'; transfer?: boolean } {
  if (mode === 'TRANSFER') return { mode: 'walk', transfer: true }
  if (mode === 'WALK' || mode === 'SUBWAY' || mode === 'BUS' || mode === 'BIKE') {
    return { mode: mode.toLowerCase() as 'walk' | 'subway' | 'bus' | 'bike' }
  }
  throw new RepositoryError('invalid-response', '지원하지 않는 이동수단 응답이에요.')
}

function routeLineName(routeId: string | undefined) {
  if (!routeId) return undefined
  const names: Record<string, string> = {
    BIKE: '자전거',
    WALK: '도보',
    '1001': '1호선',
    '1002': '2호선',
    '1003': '3호선',
    '1004': '4호선',
    '1005': '5호선',
    '1006': '6호선',
    '1007': '7호선',
    '1008': '8호선',
    '1009': '9호선',
    '1063': '경의중앙선',
    '1075': '수인분당선',
  }
  return names[routeId] || routeId
}

function endpointCoordinate(value: unknown, min: number, max: number) {
  if (value === undefined || value === null) return undefined
  if (!finite(value, min, max)) {
    throw new RepositoryError('invalid-response', '경로 지점 좌표 응답이 올바르지 않아요.')
  }
  return value as number
}

function mapEndpoint(
  rawLeg: Record<string, unknown>,
  prefix: 'from' | 'to',
): RouteEndpoint | undefined {
  const id = text(rawLeg[`${prefix}NodeId`])
  const name = text(rawLeg[`${prefix}NodeName`])
  const lat = endpointCoordinate(rawLeg[`${prefix}Lat`], -90, 90)
  const lng = endpointCoordinate(rawLeg[`${prefix}Lng`], -180, 180)
  if (!id && !name && lat === undefined && lng === undefined) return undefined
  return {
    ...(id ? { id } : {}),
    ...(name ? { name } : {}),
    ...(lat !== undefined ? { lat } : {}),
    ...(lng !== undefined ? { lng } : {}),
  }
}

function optionalDistance(value: unknown) {
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    throw new RepositoryError('invalid-response', '경로 거리 응답이 올바르지 않아요.')
  }
  return value
}

export function mapBackendRoute(value: unknown, index: number, departedAt: string): Route {
  if (!isRecord(value) || !text(value.routeType) || !finite(value.totalMinutes, 0, 24 * 60)) {
    throw new RepositoryError('invalid-response', '경로 응답이 올바르지 않아요.')
  }
  const routeType = value.routeType
  if (
    routeType !== 'SHORTEST' &&
    routeType !== 'SHORTEST_WITH_BIKE' &&
    routeType !== 'ALTERNATIVE' &&
    routeType !== 'LOW_CONGESTION'
  ) {
    throw new RepositoryError('invalid-response', '지원하지 않는 경로 유형 응답이에요.')
  }
  const rawLegs = value.legs
  if (!Array.isArray(rawLegs) || !text(value.source)) {
    throw new RepositoryError('invalid-response', '경로 응답이 올바르지 않아요.')
  }
  if (value.source !== 'ALGORITHM' && value.source !== 'MOCK') {
    throw new RepositoryError('invalid-response', '지원하지 않는 경로 출처 응답이에요.')
  }
  const legs = rawLegs.map((rawLeg) => {
    if (!isRecord(rawLeg) || !finite(rawLeg.minutes, 0, 24 * 60)) {
      throw new RepositoryError('invalid-response', '경로 구간 응답이 올바르지 않아요.')
    }
    const mappedMode = mapMode(rawLeg.mode)
    const fromName = text(rawLeg.fromNodeName) || text(rawLeg.fromNodeId) || '출발 지점'
    const toName = text(rawLeg.toNodeName) || text(rawLeg.toNodeId) || '도착 지점'
    const routeId = text(rawLeg.routeId)
    if (rawLeg.routeName != null && !text(rawLeg.routeName)) {
      throw new RepositoryError('invalid-response', '노선명 응답이 올바르지 않아요.')
    }
    const geometry = parseGeometry(rawLeg.geometry, rawLeg.geometryStatus)
    const transfer = mappedMode.transfer === true
    const from = mapEndpoint(rawLeg, 'from')
    const to = mapEndpoint(rawLeg, 'to')
    return {
      mode: mappedMode.mode,
      transfer,
      title: transfer ? `${fromName}에서 환승` : `${fromName} → ${toName}`,
      note: text(rawLeg.routeName) || routeLineName(routeId) || (transfer ? '환승' : '이동 구간'),
      distanceMeters: optionalDistance(rawLeg.distanceMeters),
      minutes: rawLeg.minutes as number,
      ...(geometry ? { geometry } : {}),
      ...(routeId ? { routeId } : {}),
      ...(from ? { from } : {}),
      ...(to ? { to } : {}),
    }
  })
  const routeGeometry = legs.flatMap((leg) => leg.geometry?.coordinates || [])
  const lineNames = [
    ...new Set(
      rawLegs
        .map((leg) =>
          isRecord(leg) ? text(leg.routeName) || routeLineName(text(leg.routeId)) : undefined,
        )
        .filter((line): line is string => !!line),
    ),
  ]
  const explicitTransfers = rawLegs.filter((leg) => isRecord(leg) && leg.mode === 'TRANSFER').length
  const transitRouteIds = rawLegs
    .filter((leg) => isRecord(leg) && leg.mode !== 'TRANSFER')
    .map((leg) => (isRecord(leg) ? text(leg.routeId) : undefined))
    .filter((routeId): routeId is string => !!routeId)
  const routeTransitions = transitRouteIds
    .slice(1)
    .reduce((count, routeId, index) => count + (routeId !== transitRouteIds[index] ? 1 : 0), 0)
  if (
    value.transferCount != null &&
    (!Number.isInteger(value.transferCount) || (value.transferCount as number) < 0)
  ) {
    throw new RepositoryError('invalid-response', '환승 횟수 응답이 올바르지 않아요.')
  }
  const transfers =
    (value.transferCount as number | undefined) ?? (explicitTransfers || routeTransitions)
  const walkingLegs = legs.filter((leg) => leg.mode === 'walk' && !leg.transfer)
  const walk =
    walkingLegs.length && walkingLegs.every((leg) => leg.distanceMeters !== undefined)
      ? walkingLegs.reduce((sum, leg) => sum + leg.distanceMeters!, 0)
      : undefined
  const label =
    routeType === 'SHORTEST'
      ? '빠른 경로'
      : routeType === 'ALTERNATIVE'
        ? '다른 경로'
        : routeType === 'LOW_CONGESTION'
          ? '덜 붐비는 경로'
          : '따릉이 포함 경로'
  return {
    routeType,
    id: `${routeType.toLowerCase()}-${index}`,
    label,
    minutes: value.totalMinutes as number,
    transfers,
    totalDistanceMeters: optionalDistance(value.totalDistanceMeters),
    ...(walk !== undefined ? { walk: Math.round(walk) } : {}),
    modes: [...new Set(legs.filter((leg) => !leg.transfer).map((leg) => leg.mode))],
    ...(lineNames.length ? { line: lineNames.join(' · ') } : {}),
    legs,
    ...(routeGeometry.length
      ? { geometry: { type: 'MultiLineString', coordinates: routeGeometry } }
      : {}),
    departedAt,
  }
}

export function mapRouteApiResponse(value: unknown, departedAt: string): Route[] {
  if (!isRecord(value) || value.success !== true || !Array.isArray(value.data)) {
    throw new RepositoryError('invalid-response', '경로 응답이 올바르지 않아요.')
  }
  return value.data.map((route, index) => mapBackendRoute(route, index, departedAt))
}
