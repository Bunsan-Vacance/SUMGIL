import type { Place } from './types'

/** 같은 장소인지 판단한다. id가 같거나 좌표가 같으면 같은 장소다. */
export function samePlace(first: Place, second: Place) {
  return (
    first.id === second.id ||
    (first.lat !== undefined &&
      first.lng !== undefined &&
      second.lat !== undefined &&
      second.lng !== undefined &&
      first.lat === second.lat &&
      first.lng === second.lng)
  )
}

/** 경로 검색에 쓸 위치(역 id 또는 유효한 좌표)가 있는지 판단한다. */
export function hasRouteLocation(place: Place) {
  const hasCoordinates =
    typeof place.lat === 'number' &&
    typeof place.lng === 'number' &&
    Number.isFinite(place.lat) &&
    Number.isFinite(place.lng) &&
    place.lat >= -90 &&
    place.lat <= 90 &&
    place.lng >= -180 &&
    place.lng <= 180
  return Boolean(place.stationId?.trim()) || hasCoordinates
}
