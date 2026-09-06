import { describe, expect, it } from 'vitest'
import { arrival, getRoutes, remaining } from './selectors'
import { bikeProposal, routes } from '../../api/mock/fixtures'

describe('경로 선택과 안내 데이터', () => {
  it('사용하지 않는 이동수단이 포함된 경로를 제외한다', () => {
    expect(getRoutes(routes, ['walk', 'bus'], 'fast').map((r) => r.id)).toEqual(['bus'])
    expect(getRoutes(routes, ['bike'], 'fast')).toEqual([])
  })
  it('대표 경로 두 개 뒤에 대안을 이어 붙이고 우선순위를 반영한다', () => {
    expect(getRoutes(routes, ['walk', 'bus', 'subway'], 'calm').map((r) => r.id)).toEqual([
      'calm',
      'fast',
      'rail',
      'bus',
    ])
  })
  it('표시 시간과 단계별 안내 시간의 합계가 일치한다', () => {
    for (const route of [...routes, bikeProposal]) {
      expect(remaining(route, 0)).toBe(route.minutes)
      expect(remaining(route, route.legs.length)).toBe(0)
      expect(remaining(route, 1)).toBe(route.minutes - route.legs[0].minutes)
    }
    expect(arrival(19)).toBe('10:00')
  })
})
