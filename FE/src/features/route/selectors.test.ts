import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  arrival,
  congestionBasisText,
  congestionGradeText,
  congestionPredictionFor,
  getRoutes,
  isCongestionPredictionDate,
  remaining,
  roundMinutes,
} from './selectors'
import { bikeProposal, routes } from '../../api/mock/fixtures'

const withoutPrediction = ({
  congestionPrediction: _prediction,
  ...route
}: (typeof routes)[number]) => route

afterEach(() => vi.useRealTimers())
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
})

describe('경로 선택과 안내 데이터', () => {
  it('서버 후보는 혼잡도 수치 없이도 추천 순서와 필터를 유지한다', () => {
    const serverRoutes = [
      {
        ...routes[1],
        id: 'low-0',
        minutes: 30,
        routeType: 'LOW_CONGESTION' as const,
        congestionPrediction: undefined,
      },
      {
        ...routes[0],
        id: 'shortest-1',
        minutes: 10,
        routeType: 'SHORTEST' as const,
        congestionPrediction: undefined,
      },
      { ...routes[3], id: 'bus-2', modes: ['bus' as const], routeType: 'ALTERNATIVE' as const },
    ]
    expect(getRoutes(serverRoutes, ['walk', 'subway'], 'calm').map((r) => r.id)).toEqual([
      'shortest-1',
      'low-0',
    ])
    expect(
      getRoutes(serverRoutes.slice(0, 2).reverse(), ['walk', 'subway'], 'fast').map((r) => r.id),
    ).toEqual(['shortest-1', 'low-0'])
  })
  it('사용하지 않는 이동수단이 포함된 경로를 제외한다', () => {
    expect(getRoutes(routes, ['walk', 'bus'], 'fast').map((r) => r.id)).toEqual(['bus'])
    expect(getRoutes(routes, ['bike'], 'fast')).toEqual([])
  })
  it('도보는 연결 구간으로 항상 허용한다', () => {
    expect(getRoutes([routes[0]], ['subway'], 'fast').map((route) => route.id)).toEqual(['fast'])
  })
  it('혼잡 예측 순위를 반영한다', () => {
    expect(getRoutes(routes, ['walk', 'bus', 'subway'], 'calm').map((r) => r.id)).toEqual([
      'calm',
      'rail',
      'bus',
      'fast',
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
    const noPredictions = routes.map(withoutPrediction)
    expect(getRoutes(noPredictions, ['walk', 'subway', 'bus'], 'calm').map((r) => r.id)).toEqual([
      'fast',
      'rail',
      'calm',
      'bus',
    ])
  })

  it('혼잡 예측은 서울 기준 오늘부터 3일 뒤까지만 사용한다', () => {
    const now = new Date('2026-09-17T00:00:00.000Z')
    expect(isCongestionPredictionDate('2026-09-17T23:00:00+09:00', now)).toBe(true)
    expect(isCongestionPredictionDate('2026-09-20T00:00:00+09:00', now)).toBe(true)
    expect(isCongestionPredictionDate('2026-09-21T00:00:00+09:00', now)).toBe(false)
    expect(isCongestionPredictionDate('2026-09-16T23:59:00+09:00', now)).toBe(false)
  })

  it('혼잡 등급과 예측 기준은 서버 enum만 표시한다', () => {
    expect(congestionGradeText('LOW')).toBe('여유')
    expect(congestionGradeText('MEDIUM')).toBe('보통')
    expect(congestionGradeText('HIGH')).toBe('혼잡')
    expect(congestionBasisText('RECENT_7D')).toBe('최근 7일 데이터 기반')
    expect(congestionBasisText('PARTIAL')).toBe('일부 기간 데이터 기반')
    expect(congestionBasisText('WEEKDAY_AVERAGE')).toBe('요일 평균 기준')
  })

  it('AVAILABLE이 아닌 상태의 수치는 예측으로 사용하지 않는다', () => {
    const route = {
      ...routes[0],
      congestionPrediction: {
        ...routes[0].congestionPrediction!,
        dataStatus: 'NO_LOOKUP' as const,
      },
    }
    expect(congestionPredictionFor(route)).toBeUndefined()
  })
})
