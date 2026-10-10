import { backendDepartureTime } from '../api/repositories'
import { hasRouteLocation, samePlace } from '../features/route/placeRules'
import { isStoredPlace } from '../features/route/placeStorage'
import type { Place } from '../features/route/types'

/** 경로 검색 조건. departureAt은 서울 로컬 'YYYY-MM-DDTHH:mm'이며 없으면 지금 출발이다. */
export interface RouteQuery {
  origin: Place
  destination: Place
  departureAt?: string
}

const DEPARTURE_AT_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/

/** URL에 넣을 필드만 고정된 순서로 뽑는다. placeUrl·dockCount·distanceMeters 등은 제외한다. */
function placeForUrl(place: Place) {
  return {
    id: place.id,
    name: place.name,
    address: place.address,
    kind: place.kind,
    ...(place.stationId !== undefined && { stationId: place.stationId }),
    ...(place.lat !== undefined && { lat: place.lat }),
    ...(place.lng !== undefined && { lng: place.lng }),
    ...(place.rentalId !== undefined && { rentalId: place.rentalId }),
  }
}

function isValidDepartureAt(value: string) {
  const match = DEPARTURE_AT_PATTERN.exec(value)
  if (!match) return false
  const [year, month, day, hour, minute] = match.slice(1).map(Number)
  if (hour > 23 || minute > 59) return false
  const date = new Date(Date.UTC(year, month - 1, day))
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
  )
}

function parsePlace(raw: string | null): Place | null {
  if (!raw) return null
  try {
    const value: unknown = JSON.parse(raw)
    if (!isStoredPlace(value) || !hasRouteLocation(value)) return null
    return value
  } catch {
    return null
  }
}

/** 'from=…&to=…&at=…' 문자열을 만든다. */
export function serializeRouteQuery(query: RouteQuery): string {
  const params = new URLSearchParams()
  params.set('from', JSON.stringify(placeForUrl(query.origin)))
  params.set('to', JSON.stringify(placeForUrl(query.destination)))
  if (query.departureAt) params.set('at', query.departureAt)
  return params.toString()
}

/** '?from=…' 또는 'from=…'을 읽는다. 하나라도 잘못되면 전체를 null로 돌려준다. */
export function parseRouteQuery(search: string): RouteQuery | null {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  const origin = parsePlace(params.get('from'))
  const destination = parsePlace(params.get('to'))
  if (!origin || !destination || samePlace(origin, destination)) return null
  const departureAt = params.get('at')
  if (departureAt === null) return { origin, destination }
  if (!isValidDepartureAt(departureAt)) return null
  return { origin, destination, departureAt }
}

/** 서울 로컬 'YYYY-MM-DDTHH:mm'을 UTC ISO 문자열로 바꾼다. */
export function departureAtToIso(local: string): string {
  return new Date(`${local}:00+09:00`).toISOString()
}

/** 서울 로컬 'YYYY-MM-DDTHH:mm'에서 'HH:mm'을 꺼낸다. */
export function departureAtToClock(local: string): string {
  return local.slice(11, 16)
}

/** ISO 시각을 서울 로컬 'YYYY-MM-DDTHH:mm'으로 바꾼다. 해석할 수 없으면 undefined다. */
export function departureAtFromIso(iso: string): string | undefined {
  return backendDepartureTime(iso)?.slice(0, 16)
}

/** 화면 상태(trip)에서 URL·공유에 쓸 검색 조건을 뽑는다. 도착지가 없거나 출발지 위치가 없으면 null이다. */
export function currentRouteQuery(trip: {
  origin: Place
  destination: Place | null
  departureTime: string | null
  departedAt?: string
}): RouteQuery | null {
  if (!trip.destination || !hasRouteLocation(trip.origin)) return null
  // 사용자가 출발 시각을 고른 경우에만 시각을 싣는다.
  const departureAt =
    trip.departureTime && trip.departedAt ? departureAtFromIso(trip.departedAt) : undefined
  return { origin: trip.origin, destination: trip.destination, departureAt }
}
