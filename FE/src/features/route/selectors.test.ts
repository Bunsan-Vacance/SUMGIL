import { describe, expect, it } from 'vitest'
import { arrival, getRoutes, remaining, roundMinutes } from './selectors'
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
    expect(arrival(11, '2026-09-09T00:30:00.000Z')).toBe('09:41')
    expect(arrival(0.5, '2026-09-09T23:59:30')).toBe('00:00')
  })

  it('분 표시만 반올림하고 내부 누적 시간은 원값을 유지한다', () => {
    const fractional = {
      ...routes[0],
      minutes: 2.716666666666667,
      legs: [
        { ...routes[0].legs[0], minutes: 1.2 },
        { ...routes[0].legs[1], minutes: 1.516666666666667 },
      ],
    }

    expect(roundMinutes(fractional.minutes)).toBe(3)
    expect(roundMinutes(2.4)).toBe(2)
    expect(remaining(fractional, 0)).toBeCloseTo(2.716666666666667)
  })

  it('혼잡도 없는 경로는 혼잡도 정렬에서 시간순으로 정렬한다', () => {
    const withoutCongestion = routes.map(
      ({ congestionPercent: _congestionPercent, ...route }) => route,
    )
    expect(
      getRoutes(withoutCongestion, ['walk', 'subway', 'bus'], 'calm').map((r) => r.id),
    ).toEqual(['fast', 'calm', 'rail', 'bus'])
  })
})
