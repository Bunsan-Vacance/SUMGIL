import type { Leg, RouteEndpoint } from '../route/types'

export interface GuidancePosition {
  latitude: number
  longitude: number
  accuracy: number
}

export const GUIDANCE_MAX_ACCURACY_METERS = 30
export const WALKING_ENDPOINT_RADIUS_METERS = 40
export const TRANSIT_ENDPOINT_RADIUS_METERS = 50
export const LOCATION_MAX_AGE_MS = 15_000

export function validCoordinates(latitude?: number, longitude?: number) {
  return (
    typeof latitude === 'number' &&
    Number.isFinite(latitude) &&
    Math.abs(latitude) <= 90 &&
    typeof longitude === 'number' &&
    Number.isFinite(longitude) &&
    Math.abs(longitude) <= 180
  )
}

export function guidanceEndpoint(leg?: Leg): RouteEndpoint | undefined {
  if (!leg) return undefined
  if (validCoordinates(leg.to?.lat, leg.to?.lng)) return leg.to
  // Only the current leg's final geometry point is a safe fallback; never another leg's station.
  const point = leg.geometry?.coordinates.at(-1)?.at(-1)
  return point && validCoordinates(point[1], point[0])
    ? { ...leg.to, lat: point[1], lng: point[0] }
    : undefined
}

export function distanceToEndpoint(position: GuidancePosition, leg?: Leg) {
  const endpoint = guidanceEndpoint(leg)
  if (!endpoint) return undefined
  const toRadians = Math.PI / 180
  const latitude = (endpoint.lat! - position.latitude) * toRadians
  const longitude = (endpoint.lng! - position.longitude) * toRadians
  const haversine =
    Math.sin(latitude / 2) ** 2 +
    Math.sin(longitude / 2) ** 2 *
      Math.cos(position.latitude * toRadians) *
      Math.cos(endpoint.lat! * toRadians)
  return 2 * 6_371_000 * Math.asin(Math.sqrt(Math.min(1, haversine)))
}

export function confirmationLabel(leg?: Leg, boarded = false) {
  switch (leg?.transitionType) {
    case 'BOARDING':
      return '탑승했어요'
    case 'ALIGHTING':
      return '하차했어요'
    case 'BIKE_RENTAL':
      return '대여했어요'
    case 'BIKE_RETURN':
      return '반납했어요'
  }
  if (leg?.mode === 'subway' && !leg.transfer && !leg.transitionType)
    return boarded ? '하차했어요' : '탑승했어요'
  return undefined
}
