import { describe, expect, it } from 'vitest'
import { featuredRoutes, sortRoutes } from './featuredRoutes'
import type { Route } from './types'

function route(
  id: string,
  minutes: number,
  percent?: number,
  routeType?: Route['routeType'],
): Route {
  return {
    id,
    label: id,
    minutes,
    transfers: 0,
    modes: ['subway'],
    legs: [],
    routeType,
    departedAt: new Date().toISOString(),
    congestionPrediction:
      percent === undefined
        ? undefined
        : {
            congestionPercent: percent,
            congestionGrade: null,
            dataStatus: 'AVAILABLE',
            predictionBasis: null,
          },
  }
}

describe('featuredRoutes', () => {
  it('가장 빠른 경로가 항상 첫 항목이다', () => {
    const result = featuredRoutes([
      route('slow', 30, 10),
      route('fast', 20, 90),
      route('mid', 25, 50),
    ])
    expect(result[0].route.id).toBe('fast')
    expect(result[0].recommendations).toEqual(['fast'])
  })

  it('덜 붐비는 경로는 예측 혼잡도가 가장 낮은 경로를 고른다', () => {
    const result = featuredRoutes([
      route('fast', 20, 90),
      route('calm', 30, 10),
      route('mid', 25, 50),
    ])
    expect(result.map((entry) => entry.route.id)).toEqual(['fast', 'calm'])
    expect(result[1].recommendations).toEqual(['calm'])
  })

  it('LOW_CONGESTION 태그가 있으면 태그 경로 중 빠른 것을 덜 붐비는 경로로 고른다', () => {
    const result = featuredRoutes([
      route('fast', 20, 90),
      route('tagged-slow', 40, 80, 'LOW_CONGESTION'),
      route('tagged-fast', 30, 95, 'LOW_CONGESTION'),
    ])
    expect(result.map((entry) => entry.route.id)).toEqual(['fast', 'tagged-fast'])
  })

  it('같은 경로가 두 기준에 모두 뽑히면 recommendations를 합친다', () => {
    const result = featuredRoutes([route('best', 20, 10), route('other', 30, 90)])
    expect(result).toHaveLength(1)
    expect(result[0].recommendations).toEqual(['fast', 'calm'])
  })

  it('경로가 없으면 빈 배열이다', () => {
    expect(featuredRoutes([])).toEqual([])
  })
})

describe('sortRoutes', () => {
  it('fast는 소요 시간순, 같으면 원래 순서를 지킨다', () => {
    const routes = [route('a', 30), route('b', 20), route('c', 20)]
    expect(sortRoutes(routes, 'fast').map((r) => r.id)).toEqual(['b', 'c', 'a'])
  })

  it('calm은 예측이 있는 경로를 혼잡도 낮은 순으로 앞에 둔다', () => {
    const routes = [route('none', 10), route('high', 20, 90), route('low', 30, 10)]
    expect(sortRoutes(routes, 'calm').map((r) => r.id)).toEqual(['low', 'high', 'none'])
  })
})
