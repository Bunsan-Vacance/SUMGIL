import { mockRouteRepository } from './mock/repositories'
import { RepositoryError } from './errors'
import {
  loadKakaoMaps,
  type KakaoMaps,
  type KakaoPlaceSearchResult,
  type KakaoAddressSearchResult,
} from '../lib/kakao/sdk'
import type {
  BikeStationRepository,
  NearbyBikeStation,
  PlaceRepository,
  RouteRepository,
  StationRepository,
  StationSearchResult,
} from './contracts'
import type {
  GeometryLineString,
  Place,
  Route,
  RouteEndpoint,
  RouteGeometry,
} from '../features/route/types'

const abortError = () => new DOMException('Aborted', 'AbortError')
export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/+$/, '') || null
export const isBackendConfigured = Boolean(apiBaseUrl)

function validCoordinate(value: string | number, min: number, max: number) {
  if (typeof value === 'string' && !value.trim()) return null
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) && number >= min && number <= max ? number : null
}

function validUrl(value?: string) {
  const trimmed = value?.trim()
  if (!trimmed) return undefined
  try {
    const url = new URL(trimmed)
    return url.protocol === 'http:' || url.protocol === 'https:' ? trimmed : undefined
  } catch {
    return undefined
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function text(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function placeFromKeyword(result: KakaoPlaceSearchResult): Place | null {
  const lat = validCoordinate(result.y, -90, 90)
  const lng = validCoordinate(result.x, -180, 180)
  const name = result.place_name?.trim()
  const address = (result.road_address_name || result.address_name || '').trim()
  const kind =
    result.category_group_name?.trim() || result.category_name?.split(' > ').at(-1) || '장소'
  if (lat === null || lng === null || !name || !address) return null
  return {
    id: result.id?.trim() || `place-${lat}-${lng}`,
    name,
    address,
    kind,
    lat,
    lng,
    placeUrl: validUrl(result.place_url),
  }
}

function placeFromAddress(result: KakaoAddressSearchResult): Place | null {
  const lat = validCoordinate(result.y, -90, 90)
  const lng = validCoordinate(result.x, -180, 180)
  const address = result.address_name?.trim()
  if (lat === null || lng === null || !address) return null
  return {
    id: `address-${lat}-${lng}`,
    name: address,
    address,
    kind: '주소',
    lat,
    lng,
  }
}

type MapsLoader = () => Promise<KakaoMaps>

export function createKakaoPlaceRepository(loadMaps: MapsLoader = loadKakaoMaps): PlaceRepository {
  return {
    search(query, signal) {
      const trimmed = query.trim()
      if (!trimmed) return Promise.resolve([])
      return new Promise<Place[]>((resolve, reject) => {
        let settled = false
        const settle = (fn: () => void) => {
          if (settled || signal.aborted) return
          settled = true
          signal.removeEventListener('abort', onAbort)
          fn()
        }
        const onAbort = () => {
          if (settled) return
          settled = true
          reject(abortError())
        }
        signal.addEventListener('abort', onAbort, { once: true })
        if (signal.aborted) {
          onAbort()
          return
        }
        loadMaps()
          .then((maps) => {
            if (signal.aborted || settled) return
            const places = new maps.services.Places()
            const geocoder = new maps.services.Geocoder()
            const searchAddress = () => {
              geocoder.addressSearch(trimmed, (results, status) => {
                if (signal.aborted || settled) return
                if (status === maps.services.Status.ZERO_RESULT) {
                  settle(() => resolve([]))
                  return
                }
                if (status !== maps.services.Status.OK) {
                  settle(() => reject(new Error('place-search-failed')))
                  return
                }
                settle(() =>
                  resolve(results.map(placeFromAddress).filter((place): place is Place => !!place)),
                )
              })
            }
            places.keywordSearch(trimmed, (results, status) => {
              if (signal.aborted || settled) return
              if (status === maps.services.Status.ZERO_RESULT) {
                searchAddress()
                return
              }
              if (status !== maps.services.Status.OK) {
                settle(() => reject(new Error('place-search-failed')))
                return
              }
              const mapped = results
                .map(placeFromKeyword)
                .filter((place): place is Place => !!place)
              if (mapped.length) settle(() => resolve(mapped))
              else searchAddress()
            })
          })
          .catch((error: unknown) => {
            if (signal.aborted || settled) return
            settle(() => reject(error))
          })
      })
    },
  }
}

function apiErrorCode(status: number, error: unknown) {
  const value = isRecord(error) ? text(error.code) : text(error)
  if (value === 'SAME_ORIGIN_DEST') return 'same-origin-destination' as const
  if (value === 'STATION_NOT_FOUND') return 'station-not-found' as const
  if (value === 'ACCESS_CANDIDATE_NOT_READY') return 'coordinate-not-ready' as const
  if (value === 'INVALID_COORDINATE') return 'invalid-coordinate' as const
  if (status === 400) return 'bad-request' as const
  if (status === 404) return 'station-not-found' as const
  return 'network' as const
}

function mapStationSearchResult(value: unknown): StationSearchResult {
  const stationId = isRecord(value) ? text(value.stationId) : undefined
  if (!isRecord(value) || !stationId || !text(value.stationName)) {
    throw new RepositoryError('invalid-response', '역 검색 응답이 올바르지 않아요.')
  }
  if (value.lineId !== undefined && value.lineId !== null && !text(value.lineId)) {
    throw new RepositoryError('invalid-response', '역 검색 응답이 올바르지 않아요.')
  }
  if (value.lineName !== undefined && value.lineName !== null && !text(value.lineName)) {
    throw new RepositoryError('invalid-response', '역 검색 응답이 올바르지 않아요.')
  }
  const hasLat = value.lat !== undefined && value.lat !== null
  const hasLng = value.lng !== undefined && value.lng !== null
  if (
    hasLat !== hasLng ||
    (hasLat && (!finite(value.lat, -90, 90) || !finite(value.lng, -180, 180)))
  ) {
    throw new RepositoryError('invalid-response', '역 검색 응답 좌표가 올바르지 않아요.')
  }
  return {
    stationId,
    stationName: text(value.stationName) as string,
    ...(text(value.lineId) ? { lineId: text(value.lineId) } : {}),
    ...(text(value.lineName) ? { lineName: text(value.lineName) } : {}),
    ...(hasLat ? { lat: value.lat as number, lng: value.lng as number } : {}),
  }
}

async function requestApi<T>(url: string, signal: AbortSignal, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      signal,
      headers: { Accept: 'application/json', ...init.headers },
    })
  } catch (error) {
    if (signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
      throw abortError()
    }
    throw new RepositoryError('network', '서버에 연결하지 못했어요.')
  }
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new RepositoryError('invalid-response', '서버 응답을 읽지 못했어요.', response.status)
  }
  if (!response.ok || !isRecord(body) || body.success !== true || !('data' in body)) {
    const error = isRecord(body) ? body.error : undefined
    const code = apiErrorCode(response.status, error)
    const message =
      code === 'same-origin-destination'
        ? '출발지와 도착지는 다른 장소를 선택해 주세요.'
        : code === 'station-not-found'
          ? '역 정보를 찾지 못했어요.'
          : code === 'coordinate-not-ready'
            ? '좌표 기반 경로는 아직 준비 중이에요.'
            : code === 'invalid-coordinate'
              ? '출발지와 도착지 좌표를 확인해 주세요.'
              : response.status === 404
                ? '역 정보를 찾지 못했어요.'
                : '서버에서 요청을 처리하지 못했어요.'
    throw new RepositoryError(code, message, response.status)
  }
  return body.data as T
}

function finite(value: unknown, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}

function backendDepartureTime(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return undefined
  const hasTimeZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed)
  if (!hasTimeZone) return trimmed.includes('T') ? trimmed : `${trimmed}T00:00:00`
  const date = new Date(trimmed)
  if (!Number.isFinite(date.getTime())) return undefined
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const valueOf = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value
  const year = valueOf('year')
  const month = valueOf('month')
  const day = valueOf('day')
  const hour = valueOf('hour')
  const minute = valueOf('minute')
  const second = valueOf('second')
  return year && month && day && hour && minute && second
    ? `${year}-${month}-${day}T${hour}:${minute}:${second}`
    : undefined
}

function parseGeometry(value: unknown, status: unknown): RouteGeometry | undefined {
  if (status !== undefined && status !== 'available' && status !== 'unavailable') {
    throw new RepositoryError('invalid-response', '지원하지 않는 경로 좌표 상태 응답이에요.')
  }
  if (status === 'unavailable') return undefined
  if (value === null || value === undefined) return undefined
  if (status === 'available' && value === null) return undefined
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

function mapBackendRoute(value: unknown, index: number, departedAt: string): Route {
  if (!isRecord(value) || !text(value.routeType) || !finite(value.totalMinutes, 0, 24 * 60)) {
    throw new RepositoryError('invalid-response', '경로 응답이 올바르지 않아요.')
  }
  const routeType = value.routeType
  if (
    routeType !== 'SHORTEST' &&
    routeType !== 'SHORTEST_WITH_BIKE' &&
    routeType !== 'ALTERNATIVE'
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
    const geometry = parseGeometry(rawLeg.geometry, rawLeg.geometryStatus)
    const transfer = mappedMode.transfer === true
    const from = mapEndpoint(rawLeg, 'from')
    const to = mapEndpoint(rawLeg, 'to')
    return {
      mode: mappedMode.mode,
      transfer,
      title: transfer ? `${fromName}에서 환승` : `${fromName} → ${toName}`,
      note: routeLineName(routeId) || (transfer ? '환승' : '이동 구간'),
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
        .map((leg) => (isRecord(leg) ? routeLineName(text(leg.routeId)) : undefined))
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
  const transfers = explicitTransfers || routeTransitions
  const label =
    routeType === 'SHORTEST'
      ? '빠른 경로'
      : routeType === 'ALTERNATIVE'
        ? '다른 경로'
        : '따릉이 포함 경로'
  return {
    id: `${routeType.toLowerCase()}-${index}`,
    label,
    minutes: value.totalMinutes as number,
    transfers,
    modes: [...new Set(legs.filter((leg) => !leg.transfer).map((leg) => leg.mode))],
    ...(lineNames.length ? { line: lineNames.join(' · ') } : {}),
    legs,
    ...(routeGeometry.length
      ? { geometry: { type: 'MultiLineString', coordinates: routeGeometry } }
      : {}),
    departedAt,
  }
}

export function createBackendStationRepository(baseUrl: string): StationRepository {
  return {
    async search(query, signal) {
      const trimmed = query.trim()
      if (!trimmed) return []
      const params = new URLSearchParams({ query: trimmed })
      try {
        const data = await requestApi<unknown>(
          `${baseUrl}/api/stations/search?${params.toString()}`,
          signal,
        )
        if (!Array.isArray(data)) {
          throw new RepositoryError('invalid-response', '역 검색 응답이 올바르지 않아요.')
        }
        return data.map(mapStationSearchResult)
      } catch (error) {
        if (signal.aborted) throw abortError()
        throw error
      }
    },
  }
}

function coordinate(place: Place, name: '출발지' | '도착지') {
  if (!finite(place.lat, -90, 90) || !finite(place.lng, -180, 180)) {
    throw new RepositoryError('invalid-coordinate', `${name} 좌표를 확인해 주세요.`)
  }
  return { lat: place.lat, lng: place.lng, name: place.name }
}

export function createBackendRouteRepository(baseUrl: string): RouteRepository {
  return {
    async search(request, signal) {
      const originStationId = request.origin.stationId
      const destStationId = request.destination.stationId
      if (originStationId && destStationId && originStationId === destStationId) {
        throw new RepositoryError('same-origin-destination', '출발역과 도착역은 달라야 해요.')
      }
      const departedAt = request.departedAt || new Date().toISOString()
      const departureTime = backendDepartureTime(departedAt)
      try {
        const params = new URLSearchParams({
          originStationId: originStationId || '',
          destStationId: destStationId || '',
        })
        if (request.modes?.length) {
          params.set('modes', request.modes.map((mode) => mode.toUpperCase()).join(','))
        }
        if (request.priority)
          params.set('priority', request.priority === 'fast' ? 'TIME' : 'COMFORT')
        if (departureTime) params.set('departureTime', departureTime)
        const data =
          originStationId && destStationId
            ? await requestApi<unknown>(`${baseUrl}/api/routes/search?${params}`, signal)
            : await requestApi<unknown>(`${baseUrl}/api/routes/search/coordinate`, signal, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  origin: coordinate(request.origin, '출발지'),
                  destination: coordinate(request.destination, '도착지'),
                  ...(request.modes?.length
                    ? { modes: request.modes.map((mode) => mode.toUpperCase()) }
                    : {}),
                  ...(request.priority
                    ? { priority: request.priority === 'fast' ? 'TIME' : 'COMFORT' }
                    : {}),
                  ...(departureTime ? { departureTime } : {}),
                }),
              })
        if (!Array.isArray(data)) {
          throw new RepositoryError('invalid-response', '경로 응답이 올바르지 않아요.')
        }
        return data.map((route, index) => mapBackendRoute(route, index, departedAt))
      } catch (error) {
        if (signal.aborted) throw abortError()
        throw error
      }
    },
  }
}

function mapNearbyStation(value: unknown): NearbyBikeStation {
  if (
    !isRecord(value) ||
    !text(value.rentalId) ||
    !text(value.name) ||
    !finite(value.lat, -90, 90) ||
    !finite(value.lng, -180, 180)
  ) {
    throw new RepositoryError('invalid-response', '대여소 응답이 올바르지 않아요.')
  }
  if (value.dockCount !== undefined && !finite(value.dockCount, 0, Number.MAX_SAFE_INTEGER)) {
    throw new RepositoryError('invalid-response', '대여소 응답이 올바르지 않아요.')
  }
  if (
    value.distanceMeters !== undefined &&
    !finite(value.distanceMeters, 0, Number.MAX_SAFE_INTEGER)
  ) {
    throw new RepositoryError('invalid-response', '대여소 응답이 올바르지 않아요.')
  }
  return {
    id: value.rentalId as string,
    name: value.name as string,
    address: text(value.address),
    lat: value.lat as number,
    lng: value.lng as number,
    dockCount: value.dockCount as number | undefined,
    distanceMeters: value.distanceMeters as number | undefined,
  }
}

export function createBackendBikeStationRepository(baseUrl: string): BikeStationRepository {
  return {
    async nearby(request, signal) {
      const params = new URLSearchParams({ lat: String(request.lat), lng: String(request.lng) })
      if (request.radiusMeters !== undefined)
        params.set('radiusMeters', String(request.radiusMeters))
      if (request.limit !== undefined) params.set('limit', String(request.limit))
      try {
        const data = await requestApi<unknown>(
          `${baseUrl}/api/bike-stations/nearby?${params}`,
          signal,
        )
        if (!Array.isArray(data)) {
          throw new RepositoryError('invalid-response', '대여소 응답이 올바르지 않아요.')
        }
        return data.map(mapNearbyStation)
      } catch (error) {
        if (signal.aborted) throw abortError()
        throw error
      }
    },
  }
}

export const routeRepository = apiBaseUrl
  ? createBackendRouteRepository(apiBaseUrl)
  : mockRouteRepository
export const bikeStationRepository = apiBaseUrl
  ? createBackendBikeStationRepository(apiBaseUrl)
  : null
export const stationRepository = apiBaseUrl ? createBackendStationRepository(apiBaseUrl) : null
export const placeRepository = createKakaoPlaceRepository()
