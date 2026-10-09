import { describe, expect, it } from 'vitest'
import type { NearbyStation } from '../../api/contracts'
import { nearbyStationToPlace, stationDisplayName, walkMinutes } from './stations'

const station: NearbyStation = {
  stationId: '222',
  stationName: '강남',
  lat: 37.4979,
  lng: 127.0276,
  distanceMeters: 180.4,
  lines: [
    { lineId: '1002', lineName: '2호선' },
    { lineId: '1077', lineName: null },
  ],
}

describe('주변 역 보조 함수', () => {
  it('도보 시간은 80m당 1분이며 최소 1분이다', () => {
    expect(walkMinutes(80)).toBe(1)
    expect(walkMinutes(120)).toBe(2)
    expect(walkMinutes(0)).toBe(1)
  })

  it('역 표시 이름은 끝에 역을 붙인다', () => {
    expect(stationDisplayName('강남')).toBe('강남역')
    expect(stationDisplayName('서울역')).toBe('서울역')
  })

  it('주변 역을 장소로 바꾸고 노선 이름을 주소로 이어 붙인다', () => {
    expect(nearbyStationToPlace(station)).toEqual({
      id: 'station:222:default',
      name: '강남',
      address: '2호선 · 1077',
      kind: '지하철역',
      stationId: '222',
      lat: 37.4979,
      lng: 127.0276,
    })
  })

  it('노선이 없으면 주소를 지하철역으로 둔다', () => {
    expect(nearbyStationToPlace({ ...station, lines: [] }).address).toBe('지하철역')
  })
})
