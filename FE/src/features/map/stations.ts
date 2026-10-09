import type { NearbyStation } from '../../api/contracts'
import type { Place } from '../route/types'

export const WALK_METERS_PER_MINUTE = 80

/** 도보 시간(분). 1분 미만이어도 1분으로 올린다. */
export function walkMinutes(distanceMeters: number): number {
  return Math.max(1, Math.ceil(distanceMeters / WALK_METERS_PER_MINUTE))
}

/** BE는 역명을 "역" 없이 저장한다. 화면에는 끝에 "역"을 붙여 보여 준다. */
export function stationDisplayName(name: string): string {
  const trimmed = name.trim()
  return trimmed.endsWith('역') ? trimmed : `${trimmed}역`
}

/** 주변 역을 경로 입력용 장소로 바꾼다. id 형태는 역 검색 결과(stationSearchResultToPlace)와 맞춘다. */
export function nearbyStationToPlace(station: NearbyStation): Place {
  const lineLabels = station.lines.map((line) => line.lineName || line.lineId)
  return {
    id: `station:${station.stationId}:default`,
    name: station.stationName,
    address: lineLabels.length ? lineLabels.join(' · ') : '지하철역',
    kind: '지하철역',
    stationId: station.stationId,
    lat: station.lat,
    lng: station.lng,
  }
}
