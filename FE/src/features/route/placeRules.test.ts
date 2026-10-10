import { describe, expect, it } from 'vitest'
import { hasRouteLocation, samePlace } from './placeRules'
import type { Place } from './types'

const base: Place = { id: 'a', name: '가', address: '서울', kind: '역' }

describe('hasRouteLocation', () => {
  it('stationId가 있으면 true다', () => {
    expect(hasRouteLocation({ ...base, stationId: 'S1' })).toBe(true)
  })

  it('공백뿐인 stationId는 위치로 보지 않는다', () => {
    expect(hasRouteLocation({ ...base, stationId: '  ' })).toBe(false)
  })

  it('유효한 좌표가 있으면 true다', () => {
    expect(hasRouteLocation({ ...base, lat: 37.5, lng: 127 })).toBe(true)
  })

  it('범위를 벗어났거나 유한하지 않은 좌표는 false다', () => {
    expect(hasRouteLocation({ ...base, lat: 91, lng: 127 })).toBe(false)
    expect(hasRouteLocation({ ...base, lat: 37.5, lng: 181 })).toBe(false)
    expect(hasRouteLocation({ ...base, lat: Number.NaN, lng: 127 })).toBe(false)
  })

  it('stationId도 좌표도 없으면 false다', () => {
    expect(hasRouteLocation(base)).toBe(false)
  })
})

describe('samePlace', () => {
  it('id가 같으면 같은 장소다', () => {
    expect(samePlace(base, { ...base, name: '나' })).toBe(true)
  })

  it('id가 달라도 좌표가 같으면 같은 장소다', () => {
    const first = { ...base, lat: 37.5, lng: 127 }
    expect(samePlace(first, { ...first, id: 'b' })).toBe(true)
  })

  it('id와 좌표가 모두 다르면 다른 장소다', () => {
    const first = { ...base, lat: 37.5, lng: 127 }
    expect(samePlace(first, { ...first, id: 'b', lat: 37.6 })).toBe(false)
  })

  it('한쪽에 좌표가 없으면 id만 비교한다', () => {
    expect(samePlace({ ...base, lat: 37.5, lng: 127 }, { ...base, id: 'b' })).toBe(false)
  })
})
