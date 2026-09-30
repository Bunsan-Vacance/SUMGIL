import { describe, expect, it } from 'vitest'
import { buildCheckpointDelays } from './rerouteSchedule'
import type { Leg, Route } from '../route/types'

const MIN = 60_000

function subway(minutes: number, waitMinutes?: number): Leg {
  return {
    mode: 'subway',
    title: '지하철',
    note: '',
    minutes,
    ...(waitMinutes === undefined ? {} : { waitMinutes }),
    from: { id: 'a', lat: 37.5, lng: 127.0 },
    to: { id: 'b', lat: 37.5, lng: 127.1 },
  }
}

const walkToRental = (minutes: number): Leg => ({
  mode: 'walk',
  title: '대여소로 이동',
  note: '',
  minutes,
  from: { id: 'ND-1', lat: 37.5, lng: 127.0 },
  to: { id: 'r-a', rentalId: 'ST-1', lat: 37.5, lng: 127.1 },
})

const bike: Leg = {
  mode: 'bike',
  title: '따릉이',
  note: '',
  minutes: 6,
  from: { id: 'r-a', rentalId: 'ST-1' },
  to: { id: 'r-b', rentalId: 'ST-2' },
}

function routeOf(legs: Leg[]): Route {
  return { id: 'r', label: '경로', minutes: 0, transfers: 0, modes: [], legs }
}

describe('buildCheckpointDelays', () => {
  it('각 지하철 leg 끝 120초 전에 체크포인트를 둔다(ETA 30분 이하면 horizon 없음)', () => {
    const route = routeOf([subway(10, 3), subway(8), walkToRental(4), bike])
    expect(buildCheckpointDelays(route, 0)).toEqual([11 * MIN, 19 * MIN])
  })

  it('ETA가 30분을 넘으면 horizon 체크포인트와 긴 leg 중간 체크포인트를 더한다', () => {
    const route = routeOf([subway(25), subway(11), walkToRental(4), bike])
    expect(buildCheckpointDelays(route, 0)).toEqual([10 * MIN, 12.5 * MIN, 23 * MIN, 34 * MIN])
  })

  it('0 이하 지연은 버리고, 정렬·중복 제거한다', () => {
    // 첫 leg 1분 → 끝 120초 전은 -1분이라 버려진다. 둘째 leg 끝(2+... )과 겹치는 값은 하나만 남는다.
    const route = routeOf([subway(1), subway(5), walkToRental(4), bike])
    expect(buildCheckpointDelays(route, 0)).toEqual([4 * MIN])
    const dup = routeOf([subway(20), subway(1), walkToRental(30), bike])
    const delays = buildCheckpointDelays(dup, 0)
    expect(delays).toEqual([...new Set(delays)].sort((a, b) => a - b))
    expect(delays.every((d) => d > 0)).toBe(true)
  })

  it('step 이후 leg만 기준으로 계산한다', () => {
    const route = routeOf([subway(10, 3), subway(8), walkToRental(4), bike])
    expect(buildCheckpointDelays(route, 1)).toEqual([6 * MIN])
  })

  it('경계가 없거나 route가 null이면 빈 배열', () => {
    expect(buildCheckpointDelays(null, 0)).toEqual([])
    expect(buildCheckpointDelays(routeOf([subway(10)]), 0)).toEqual([])
  })

  it('최대 8개까지, 이른 것부터 남긴다', () => {
    const legs = Array.from({ length: 12 }, () => subway(10))
    const delays = buildCheckpointDelays(routeOf([...legs, walkToRental(4), bike]), 0)
    expect(delays).toHaveLength(8)
    expect(delays[0]).toBe(8 * MIN)
  })
})
