import { describe, expect, it } from 'vitest'
import { bikeStations, parseBikeStations, searchBikeStations, stationToPlace } from './bikeStations'

describe('따릉이 대여소 데이터', () => {
  it('정적 데이터는 좌표가 있는 3,353개 대여소를 제공한다', () => {
    expect(bikeStations).toHaveLength(3353)
    expect(new Set(bikeStations.map((station) => station.id)).size).toBe(3353)
    expect(
      bikeStations.every((station) => station.address && station.lat !== 0 && station.lng !== 0),
    ).toBe(true)
  })

  it('경계에서 잘못된 ID·주소·좌표를 거부한다', () => {
    expect(() =>
      parseBikeStations([
        { id: '', name: '이름', address: '주소', lat: 37.5, lng: 127 },
        { id: 'ST-1', name: '이름', address: '주소', lat: 0, lng: 127 },
      ]),
    ).toThrow()
  })

  it('ID·주소·대여소명을 공백과 대소문자 차이 없이 검색하고 20개로 제한한다', () => {
    const stations = Array.from({ length: 21 }, (_, index) => ({
      id: `ST-${index}`,
      name: index === 0 ? '강남역 1번 출구' : `대여소 ${index}`,
      address: index === 0 ? '서울 강남구 테헤란로' : `서울 주소 ${index}`,
      lat: 37.5,
      lng: 127,
    }))

    expect(searchBikeStations(' st- 0 ', stations)).toEqual([stationToPlace(stations[0])])
    expect(searchBikeStations('강 남 역', stations)).toEqual([stationToPlace(stations[0])])
    expect(searchBikeStations('서울 주소', stations)).toHaveLength(20)
  })
})
