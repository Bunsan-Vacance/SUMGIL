import { describe, expect, it } from 'vitest'
import type { Route } from './types'
import { bikePredictionTargetForRoute, bikeStockTargetForRoute } from './bikeAvailability'

const route: Route = {
  id: 'bike-route',
  label: '따릉이 경로',
  minutes: 14,
  transfers: 0,
  modes: ['walk', 'bike'],
  departedAt: '2026-09-24T08:30:00+09:00',
  legs: [
    { mode: 'walk', title: '대여소까지 이동', note: '', minutes: 3 },
    {
      mode: 'bike',
      title: '따릉이 이용',
      note: '',
      minutes: 8,
      from: { name: '출발 대여소', rentalId: 'ST-1' },
      to: { name: '도착 대여소', rentalId: 'ST-2' },
    },
  ],
}

describe('BIKE 경로 조회 대상', () => {
  it('첫 BIKE 구간 이전 minutes 합으로 도착 시각을 계산한다', () => {
    expect(bikePredictionTargetForRoute(route)).toMatchObject({
      rentalId: 'ST-1',
      arrivalTime: '2026-09-23T23:33:00.000Z',
    })
  })

  it('출발 대여소 stock 대상만 반환한다', () => {
    expect(bikeStockTargetForRoute(route)).toMatchObject({
      rentalId: 'ST-1',
      leg: { to: { rentalId: 'ST-2' } },
    })
  })

  it('명시적인 출발 rentalId가 없으면 prediction과 stock 대상을 만들지 않는다', () => {
    const withoutId: Route = {
      ...route,
      legs: route.legs.map((leg) =>
        leg.mode === 'bike' ? { ...leg, from: { name: '대여소' } } : leg,
      ),
    }
    expect(bikePredictionTargetForRoute(withoutId)).toBeNull()
    expect(bikeStockTargetForRoute(withoutId)).toBeNull()
  })
})
