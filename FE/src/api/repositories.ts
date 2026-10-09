import { mockRouteRepository, routeSearchMockRepository } from './mock/repositories'
import { bikePredictionMockRepository } from './mock/bikePrediction'
import { bikeStockMockRepository } from './mock/bikeStock'
import { RepositoryError } from './errors'
import { mapBackendRoute } from './routeMapper'
import { createBackendBikePredictionRepository } from './bikePrediction'
import { createBackendOpsRepository } from './ops'
import { opsMockRepository } from './mock/opsRepositories'
import {
  loadKakaoMaps,
  type KakaoMaps,
  type KakaoPlaceSearchResult,
  type KakaoAddressSearchResult,
} from '../lib/kakao/sdk'
import type {
  BikeStationRepository,
  BikeStock,
  BikeStockStatus,
  NearbyBikeStation,
  NearbyStation,
  NearbyStationLine,
  OpsRepository,
  PlaceRepository,
  RouteRepository,
  StationRepository,
  StationSearchResult,
} from './contracts'
import type { Place } from '../features/route/types'

const abortError = () => new DOMException('Aborted', 'AbortError')
export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/+$/, '') || null
export const isBackendConfigured = Boolean(apiBaseUrl)
export const isRouteSearchMockEnabled =
  import.meta.env.VITE_ROUTE_SEARCH_MOCK?.trim().toLowerCase() === 'true'
export const isBikePredictionMockEnabled =
  import.meta.env.VITE_BIKE_PREDICTION_MOCK?.trim().toLowerCase() === 'true'
export const isBikeStockMockEnabled =
  import.meta.env.VITE_BIKE_STOCK_MOCK?.trim().toLowerCase() === 'true'
export const isOpsMockEnabled = import.meta.env.VITE_OPS_MOCK?.trim().toLowerCase() === 'true'

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
  if (value === 'ROUTE_DATA_NOT_READY') return 'route-data-not-ready' as const
  if (value === 'ACCESS_CANDIDATE_NOT_FOUND') return 'access-candidate-not-found' as const
  if (value === 'OUT_OF_SERVICE_AREA') return 'out-of-service-area' as const
  if (value === 'SERVICE_ENDED') return 'service-ended' as const
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

export async function requestApi<T>(
  url: string,
  signal: AbortSignal,
  init: RequestInit = {},
  allowEmpty = false,
): Promise<T> {
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
  if (
    !response.ok ||
    !isRecord(body) ||
    body.success !== true ||
    (!allowEmpty && !('data' in body))
  ) {
    const error = isRecord(body) ? body.error : undefined
    const code = apiErrorCode(response.status, error)
    const message =
      code === 'route-data-not-ready'
        ? '경로 데이터를 준비하고 있어요. 잠시 후 다시 시도해 주세요.'
        : code === 'access-candidate-not-found'
          ? '출발지나 도착지 주변에 연결되는 경로가 없어요.'
          : code === 'out-of-service-area'
            ? '서비스 지역 밖이라 경로를 찾지 못했어요.'
            : code === 'service-ended'
              ? '선택한 출발 시간에는 이용할 수 없어요.'
              : code === 'same-origin-destination'
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

export function backendDepartureTime(value: string) {
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

function mapNearbyStationLine(value: unknown): NearbyStationLine {
  if (!isRecord(value) || !text(value.lineId)) {
    throw new RepositoryError('invalid-response', '주변 역 응답이 올바르지 않아요.')
  }
  if (
    value.lineName !== null &&
    value.lineName !== undefined &&
    typeof value.lineName !== 'string'
  ) {
    throw new RepositoryError('invalid-response', '주변 역 응답이 올바르지 않아요.')
  }
  return { lineId: text(value.lineId) as string, lineName: text(value.lineName) ?? null }
}

// stationId는 불투명 문자열이다. 숫자·영문자가 섞이므로 정수 파싱이나 정규식 검증을 하지 않는다.
function mapNearbyStationResult(value: unknown): NearbyStation {
  if (
    !isRecord(value) ||
    !text(value.stationId) ||
    !text(value.stationName) ||
    !finite(value.lat, -90, 90) ||
    !finite(value.lng, -180, 180) ||
    !finite(value.distanceMeters, 0, Number.MAX_SAFE_INTEGER) ||
    !Array.isArray(value.lines)
  ) {
    throw new RepositoryError('invalid-response', '주변 역 응답이 올바르지 않아요.')
  }
  return {
    stationId: text(value.stationId) as string,
    stationName: text(value.stationName) as string,
    lat: value.lat as number,
    lng: value.lng as number,
    distanceMeters: value.distanceMeters as number,
    lines: value.lines.map(mapNearbyStationLine),
  }
}

export function createBackendStationRepository(baseUrl: string): StationRepository {
  return {
    async nearby(request, signal) {
      if (!finite(request.lat, -90, 90) || !finite(request.lng, -180, 180)) {
        throw new RepositoryError('bad-request', '좌표를 확인해 주세요.')
      }
      const params = new URLSearchParams({ lat: String(request.lat), lng: String(request.lng) })
      if (request.radiusMeters !== undefined)
        params.set('radiusMeters', String(request.radiusMeters))
      if (request.limit !== undefined) params.set('limit', String(request.limit))
      try {
        const data = await requestApi<unknown>(
          `${baseUrl}/api/stations/nearby?${params.toString()}`,
          signal,
        )
        if (!Array.isArray(data)) {
          throw new RepositoryError('invalid-response', '주변 역 응답이 올바르지 않아요.')
        }
        return data.map(mapNearbyStationResult)
      } catch (error) {
        if (signal.aborted) throw abortError()
        throw error
      }
    },
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

const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/

function isIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    ISO_TIMESTAMP.test(value) &&
    Number.isFinite(new Date(value).getTime())
  )
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
  const stock = value.availableBikes
  if (
    stock !== undefined &&
    stock !== null &&
    (!Number.isSafeInteger(stock) || (stock as number) < 0)
  ) {
    throw new RepositoryError('invalid-response', '대여소 응답이 올바르지 않아요.')
  }
  if (
    value.stockUpdatedAt !== undefined &&
    value.stockUpdatedAt !== null &&
    !isIsoTimestamp(value.stockUpdatedAt)
  ) {
    throw new RepositoryError('invalid-response', '대여소 응답이 올바르지 않아요.')
  }
  const hasStock = typeof stock === 'number'
  return {
    id: value.rentalId as string,
    name: value.name as string,
    address: text(value.address),
    lat: value.lat as number,
    lng: value.lng as number,
    dockCount: value.dockCount as number | undefined,
    distanceMeters: value.distanceMeters as number | undefined,
    ...(stock !== undefined
      ? {
          availableBikes: stock as number | null,
          stockUpdatedAt: hasStock
            ? ((value.stockUpdatedAt as string | null | undefined) ?? null)
            : null,
        }
      : {}),
  }
}

function mapBikeStock(value: unknown): BikeStock {
  if (!isRecord(value) || !text(value.rentalId)) {
    throw new RepositoryError('invalid-response', '따릉이 재고 응답이 올바르지 않아요.')
  }
  if (value.status !== 'AVAILABLE' && value.status !== 'STALE' && value.status !== 'UNAVAILABLE') {
    throw new RepositoryError('invalid-response', '따릉이 재고 상태 응답이 올바르지 않아요.')
  }
  const hasCount = Number.isInteger(value.availableBikes) && (value.availableBikes as number) >= 0
  const hasRackCount =
    value.rackCount === null ||
    (Number.isInteger(value.rackCount) && (value.rackCount as number) >= 0)
  if (value.rackCount !== undefined && !hasRackCount) {
    throw new RepositoryError('invalid-response', '따릉이 거치대 수 응답이 올바르지 않아요.')
  }
  const timestamp = text(value.stockUpdatedAt)
  const hasValidTimestamp =
    !!timestamp &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/.test(timestamp) &&
    Number.isFinite(new Date(timestamp).getTime())
  if (value.status !== 'UNAVAILABLE' && (!hasCount || !hasValidTimestamp)) {
    throw new RepositoryError('invalid-response', '따릉이 재고 응답이 올바르지 않아요.')
  }
  if (
    value.status === 'UNAVAILABLE' &&
    (value.availableBikes != null || value.stockUpdatedAt != null || value.rackCount != null)
  ) {
    throw new RepositoryError('invalid-response', '따릉이 재고 응답이 올바르지 않아요.')
  }
  return {
    rentalId: value.rentalId as string,
    availableBikes: hasCount ? (value.availableBikes as number) : null,
    stockUpdatedAt: hasValidTimestamp ? timestamp : null,
    status: value.status as BikeStockStatus,
    ...(value.rackCount !== undefined ? { rackCount: value.rackCount as number | null } : {}),
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
    async stock(rentalId, signal) {
      const id = rentalId.trim()
      if (!id) throw new RepositoryError('bad-request', '대여소 정보를 확인해 주세요.')
      try {
        const data = await requestApi<unknown>(
          `${baseUrl}/api/bike-stations/${encodeURIComponent(id)}/stock`,
          signal,
        )
        const stock = mapBikeStock(data)
        if (stock.rentalId !== id) {
          throw new RepositoryError('invalid-response', '따릉이 대여소 응답이 요청과 다릅니다.')
        }
        return stock
      } catch (error) {
        if (signal.aborted) throw abortError()
        if (error instanceof RepositoryError && error.status === 404) {
          throw new RepositoryError('bike-station-not-found', '따릉이 대여소를 찾지 못했어요.', 404)
        }
        throw error
      }
    },
  }
}

export const routeRepository = isRouteSearchMockEnabled
  ? routeSearchMockRepository
  : apiBaseUrl
    ? createBackendRouteRepository(apiBaseUrl)
    : mockRouteRepository
export const bikeStockRepository = isBikeStockMockEnabled
  ? bikeStockMockRepository
  : apiBaseUrl
    ? createBackendBikeStationRepository(apiBaseUrl)
    : null
export const bikeStationRepository = bikeStockRepository
export const bikePredictionRepository = isBikePredictionMockEnabled
  ? bikePredictionMockRepository
  : apiBaseUrl
    ? createBackendBikePredictionRepository(apiBaseUrl)
    : null
export const stationRepository = apiBaseUrl ? createBackendStationRepository(apiBaseUrl) : null
export const placeRepository = createKakaoPlaceRepository()
// 운영자 뷰: mock은 VITE_OPS_MOCK=true일 때만 쓴다. 실제 저장소 실패를 mock으로 대체하지 않는다.
export const opsRepository: OpsRepository | null = isOpsMockEnabled
  ? opsMockRepository
  : apiBaseUrl
    ? createBackendOpsRepository(apiBaseUrl)
    : null
