import { describe, expect, it } from 'vitest'
import {
  departureAtFromIso,
  departureAtToClock,
  departureAtToIso,
  parseRouteQuery,
  serializeRouteQuery,
} from './routeQuery'
import type { Place } from '../features/route/types'

const station: Place = {
  id: 'station-1',
  name: '역삼역',
  address: '서울 강남구 테헤란로 지하 156',
  kind: '역',
  stationId: 'S-222',
}
const point: Place = {
  id: 'kakao-1',
  name: '강남 카페',
  address: '서울 강남구 역삼동 1',
  kind: '장소',
  lat: 37.5,
  lng: 127.03,
}
const bike: Place = {
  id: 'bike-1',
  name: '역삼역 1번 출구 대여소',
  address: '서울 강남구 역삼동',
  kind: '따릉이',
  lat: 37.501,
  lng: 127.036,
  rentalId: 'ST-100',
}

function encode(from: unknown, to: unknown, at?: string) {
  const params = new URLSearchParams()
  params.set('from', typeof from === 'string' ? from : JSON.stringify(from))
  params.set('to', typeof to === 'string' ? to : JSON.stringify(to))
  if (at !== undefined) params.set('at', at)
  return params.toString()
}

describe('경로 검색 조건 직렬화·파싱', () => {
  it('역·좌표 장소를 왕복한다', () => {
    const query = { origin: station, destination: point }
    expect(parseRouteQuery(serializeRouteQuery(query))).toEqual(query)
  })

  it('따릉이 rentalId를 보존한다', () => {
    const query = { origin: bike, destination: station }
    expect(parseRouteQuery(serializeRouteQuery(query))).toEqual(query)
  })

  it('at이 있으면 함께 왕복하고 없으면 생략한다', () => {
    const withAt = serializeRouteQuery({
      origin: station,
      destination: point,
      departureAt: '2026-10-09T18:30',
    })
    expect(new URLSearchParams(withAt).get('at')).toBe('2026-10-09T18:30')
    expect(parseRouteQuery(withAt)?.departureAt).toBe('2026-10-09T18:30')

    const withoutAt = serializeRouteQuery({ origin: station, destination: point })
    expect(new URLSearchParams(withoutAt).has('at')).toBe(false)
    expect(parseRouteQuery(withoutAt)).not.toHaveProperty('departureAt')
  })

  it('물음표가 붙은 문자열도 읽는다', () => {
    const search = serializeRouteQuery({ origin: station, destination: point })
    expect(parseRouteQuery(`?${search}`)).toEqual({ origin: station, destination: point })
  })

  it('필드 순서가 고정이고 불필요한 필드는 뺀다', () => {
    const search = serializeRouteQuery({
      origin: { ...bike, placeUrl: 'https://example.com', dockCount: 3, distanceMeters: 10 },
      destination: { ...station, distanceMeters: 5 },
    })
    const params = new URLSearchParams(search)
    expect(params.get('from')).toBe(
      '{"id":"bike-1","name":"역삼역 1번 출구 대여소","address":"서울 강남구 역삼동","kind":"따릉이","lat":37.501,"lng":127.036,"rentalId":"ST-100"}',
    )
    expect(params.get('to')).toBe(
      '{"id":"station-1","name":"역삼역","address":"서울 강남구 테헤란로 지하 156","kind":"역","stationId":"S-222"}',
    )
  })

  describe('잘못된 값은 전체 null이다', () => {
    it('JSON이 깨졌다', () => {
      expect(parseRouteQuery(encode('{broken', point))).toBeNull()
      expect(parseRouteQuery(encode(station, '[1,2]'))).toBeNull()
    })

    it('address가 없다', () => {
      const { address: _address, ...noAddress } = station
      expect(parseRouteQuery(encode(noAddress, point))).toBeNull()
    })

    it('stationId와 좌표가 모두 없다', () => {
      const { stationId: _stationId, ...noLocation } = station
      expect(parseRouteQuery(encode(noLocation, point))).toBeNull()
    })

    it('출발과 도착이 같은 장소다', () => {
      expect(parseRouteQuery(encode(station, { ...station }))).toBeNull()
      expect(parseRouteQuery(encode(point, { ...point, id: 'other' }))).toBeNull()
    })

    it('at 형식이 틀렸다', () => {
      expect(parseRouteQuery(encode(station, point, '2026-10-09 18:30'))).toBeNull()
      expect(parseRouteQuery(encode(station, point, '18:30'))).toBeNull()
      expect(parseRouteQuery(encode(station, point, ''))).toBeNull()
    })

    it('at 날짜가 유효하지 않다', () => {
      expect(parseRouteQuery(encode(station, point, '2026-13-40T25:61'))).toBeNull()
      expect(parseRouteQuery(encode(station, point, '2026-02-30T10:00'))).toBeNull()
      expect(parseRouteQuery(encode(station, point, '2026-10-09T24:00'))).toBeNull()
    })

    it('둘 중 하나만 있다', () => {
      expect(parseRouteQuery(`from=${encodeURIComponent(JSON.stringify(station))}`)).toBeNull()
      expect(parseRouteQuery(`to=${encodeURIComponent(JSON.stringify(point))}`)).toBeNull()
      expect(parseRouteQuery('')).toBeNull()
    })
  })
})

describe('출발 시각 변환', () => {
  it('서울 로컬을 UTC ISO로 바꾼다', () => {
    expect(departureAtToIso('2026-10-09T18:30')).toBe('2026-10-09T09:30:00.000Z')
  })

  it('HH:mm을 꺼낸다', () => {
    expect(departureAtToClock('2026-10-09T18:30')).toBe('18:30')
  })

  it('ISO를 서울 로컬로 바꾼다', () => {
    expect(departureAtFromIso('2026-10-09T09:30:00.000Z')).toBe('2026-10-09T18:30')
    expect(departureAtFromIso('2026-10-09T23:30:00.000Z')).toBe('2026-10-10T08:30')
  })

  it('해석할 수 없는 ISO는 undefined다', () => {
    expect(departureAtFromIso('')).toBeUndefined()
    expect(departureAtFromIso('not-a-dateZ')).toBeUndefined()
  })
})
