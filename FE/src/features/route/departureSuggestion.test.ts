import { describe, expect, it } from 'vitest'
import {
  gradeIndex,
  pickSuggestion,
  shiftDeparture,
  suggestionView,
  SUGGESTION_OFFSETS_MIN,
  type DepartureSuggestion,
} from './departureSuggestion'
import type { Leg, Route } from './types'

const subwayLeg = (routeId = '1002'): Leg => ({
  mode: 'subway',
  title: 'A → B',
  note: '2호선',
  routeId,
  minutes: 10,
  from: { id: 'A', name: 'A' },
  to: { id: 'B', name: 'B' },
})

/** percent 30/80/120 → 여유/보통/혼잡. undefined면 예측 근거 없음. */
function route(id: string, minutes: number, percent?: number, legs: Leg[] = [subwayLeg()]): Route {
  return {
    id,
    label: id,
    minutes,
    transfers: 0,
    modes: ['subway'],
    legs,
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

const alt = (offsetMin: number, routes: Route[]) => ({
  offsetMin,
  clock: offsetMin === 10 ? '18:50' : '19:00',
  routes,
})

describe('shiftDeparture', () => {
  it('서울 시각으로 분을 더해 iso와 HH:mm을 돌려준다', () => {
    const shifted = shiftDeparture('2026-10-12T18:40:00+09:00', 20)
    expect(shifted?.clock).toBe('19:00')
    expect(shifted?.iso).toBe(new Date('2026-10-12T19:00:00+09:00').toISOString())
  })

  it('서울 기준 날짜가 바뀌면 null이다', () => {
    expect(shiftDeparture('2026-10-12T23:50:00+09:00', 20)).toBeNull()
    expect(shiftDeparture('2026-10-12T23:40:00+09:00', 10)?.clock).toBe('23:50')
  })

  it('UTC 표기여도 서울 날짜로 판단한다', () => {
    // 2026-10-12T14:50Z = 서울 23:50
    expect(shiftDeparture('2026-10-12T14:50:00.000Z', 20)).toBeNull()
  })

  it('해석할 수 없는 값은 null이다', () => {
    expect(shiftDeparture('not-a-date', 10)).toBeNull()
  })

  it('오프셋은 10분, 20분이다', () => {
    expect(SUGGESTION_OFFSETS_MIN).toEqual([10, 20])
  })
})

describe('gradeIndex', () => {
  it('예측 등급을 여유 0 · 보통 1 · 혼잡 2로 돌려준다', () => {
    expect(gradeIndex(route('a', 20, 30))).toBe(0)
    expect(gradeIndex(route('a', 20, 80))).toBe(1)
    expect(gradeIndex(route('a', 20, 120))).toBe(2)
  })

  it('예측 근거가 없으면 undefined다', () => {
    expect(gradeIndex(route('a', 20))).toBeUndefined()
  })
})

describe('pickSuggestion', () => {
  const base = route('base', 30, 120)

  it('한 등급 이상 낮아진 같은 경로만 채택한다', () => {
    const result = pickSuggestion(base, [alt(20, [route('later', 48, 30)])])
    expect(result).toEqual({
      offsetMin: 20,
      clock: '19:00',
      fromGrade: 'CONGESTED',
      toGrade: 'RELAXED',
      arrivalDeltaMin: 38,
    })
  })

  it('동급이거나 더 혼잡하면 제안하지 않는다', () => {
    expect(pickSuggestion(base, [alt(10, [route('same', 30, 120)]), alt(20, [])])).toBeNull()
    expect(pickSuggestion(route('mid', 30, 80), [alt(10, [route('worse', 30, 120)])])).toBeNull()
  })

  it('구간 서명이 다른 경로는 후보가 아니다', () => {
    const other = route('other', 30, 30, [subwayLeg('1003')])
    expect(pickSuggestion(base, [alt(10, [other])])).toBeNull()
  })

  it('같은 서명 경로가 여러 개면 가장 낮은 등급을 쓴다', () => {
    const result = pickSuggestion(base, [
      alt(10, [route('x', 30, 80), route('y', 31, 30), route('z', 32, 120)]),
    ])
    expect(result?.toGrade).toBe('RELAXED')
    expect(result?.arrivalDeltaMin).toBe(11)
  })

  it('개선 폭이 큰 후보를 우선한다', () => {
    const result = pickSuggestion(base, [
      alt(10, [route('a', 30, 80)]),
      alt(20, [route('b', 30, 30)]),
    ])
    expect(result?.offsetMin).toBe(20)
  })

  it('개선 폭이 같으면 이른 시각을 고른다', () => {
    const result = pickSuggestion(base, [
      alt(20, [route('b', 30, 30)]),
      alt(10, [route('a', 30, 30)]),
    ])
    expect(result?.offsetMin).toBe(10)
  })

  it('기준 경로 근거가 없으면 null이다', () => {
    expect(pickSuggestion(route('nobase', 30), [alt(10, [route('a', 30, 30)])])).toBeNull()
  })

  it('후보에 근거가 없으면 채택하지 않는다', () => {
    expect(pickSuggestion(base, [alt(10, [route('a', 30)])])).toBeNull()
  })

  it('기준이 이미 여유면 null이다', () => {
    expect(pickSuggestion(route('calm', 30, 30), [alt(10, [route('a', 30, 30)])])).toBeNull()
  })

  it('도착 델타는 오프셋에 소요 시간 차를 더한 값이고 음수가 될 수 있다', () => {
    const result = pickSuggestion(base, [alt(10, [route('fast', 17, 30)])])
    expect(result?.arrivalDeltaMin).toBe(-3)
  })
})

describe('suggestionView', () => {
  const suggestion = (arrivalDeltaMin: number): DepartureSuggestion => ({
    offsetMin: 20,
    clock: '19:00',
    fromGrade: 'CONGESTED',
    toGrade: 'RELAXED',
    arrivalDeltaMin,
  })

  it('늦게 도착하는 경우 문구', () => {
    expect(suggestionView(suggestion(18))).toEqual({
      title: '20분 늦게 출발하면',
      fromLabel: '혼잡',
      fromColor: '#b91c1c',
      toLabel: '여유',
      toColor: '#1d4ed8',
      detail: '19:00 출발 · 도착 +18분 · 예측 기준',
      ariaLabel:
        '20분 늦게 19:00에 출발하면 혼잡에서 여유, 도착 18분 늦어짐, 예측 기준. 이 시각으로 다시 찾기',
    })
  })

  it('빨리 도착하는 경우 U+2212 마이너스를 쓴다', () => {
    const view = suggestionView(suggestion(-3))
    expect(view.detail).toBe('19:00 출발 · 도착 −3분 · 예측 기준')
    expect(view.ariaLabel).toContain('도착 3분 빨라짐')
  })

  it('차이가 없으면 도착 시각 비슷', () => {
    const view = suggestionView(suggestion(0))
    expect(view.detail).toBe('19:00 출발 · 도착 시각 비슷 · 예측 기준')
    expect(view.ariaLabel).toContain('도착 시각 비슷, 예측 기준')
  })
})
