import { describe, expect, it } from 'vitest'
import {
  bikeStations,
  nearbyStationToBikeStation,
  parseBikeStations,
  stationToPlace,
} from './bikeStations'

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

  it('ID fallback 이름을 화면용 대여소명으로 바꾼다', () => {
    const station = {
      id: 'ST-995',
      name: '따릉이 대여소 ST-995',
      address: '서울특별시 양천구 중앙로 153',
      lat: 37.51,
      lng: 126.85,
    }

    expect(stationToPlace(station).name).toBe('따릉이 대여소')
  })

  it('nearby 메타데이터의 0과 거리 값을 지도 장소까지 보존한다', () => {
    const station = nearbyStationToBikeStation({
      id: 'ST-0',
      name: '대여소',
      lat: 37.51,
      lng: 126.98,
      dockCount: 0,
      distanceMeters: 42.5,
    })

    expect(station).toMatchObject({ dockCount: 0, distanceMeters: 42.5 })
    expect(stationToPlace(station)).toMatchObject({ dockCount: 0, distanceMeters: 42.5 })
  })
})
