import { describe, expect, it } from 'vitest'
import type { TrainArrival } from '../../api/guidance'
import { formatClock, groupArrivalsByDirection } from './stationArrivals'

const now = new Date('2026-10-09T01:00:00.000Z')
const train = (trainId: string, direction: string, minutes: number): TrainArrival => ({
  trainId,
  direction,
  arrivalTime: new Date(now.getTime() + minutes * 60000).toISOString(),
  updatedAt: now.toISOString(),
  source: 'LIVE',
})

describe('역 도착 정보 정리', () => {
  it('방면별로 가장 빠른 두 대를 시각순으로 묶고 방면은 등장 순서를 따른다', () => {
    const result = groupArrivalsByDirection(
      [train('a', '내선', 9), train('b', '외선', 3), train('c', '내선', 2), train('d', '내선', 5)],
      now,
    )
    expect(result.map((item) => item.direction)).toEqual(['내선', '외선'])
    expect(result[0].trains.map((item) => item.etaMinutes)).toEqual([2, 5])
    expect(result[0].trains[0].etaLabel).toBe('2분 후')
  })

  it('지난 열차는 제외하고 1분 미만은 곧 도착이다', () => {
    const result = groupArrivalsByDirection([train('a', '내선', -3), train('b', '내선', 0.2)], now)
    expect(result[0].trains).toHaveLength(1)
    expect(result[0].trains[0]).toMatchObject({ etaMinutes: 0, etaLabel: '곧 도착' })
    expect(groupArrivalsByDirection([train('a', '내선', -3)], now)).toEqual([])
  })

  it('방면당 표시 개수를 바꿀 수 있다', () => {
    const result = groupArrivalsByDirection(
      [train('a', '내선', 1), train('b', '내선', 2), train('c', '내선', 3)],
      now,
      3,
    )
    expect(result[0].trains).toHaveLength(3)
  })

  it('시각을 서울 기준으로 표시하고 잘못된 값은 빈 문자열이다', () => {
    expect(formatClock('2026-10-09T01:05:09.000Z', false)).toBe('10:05')
    expect(formatClock('2026-10-09T01:05:09.000Z', true)).toBe('10:05:09')
    expect(formatClock('2026-10-08T15:00:00.000Z', false)).toBe('00:00')
    expect(formatClock('not-a-date', false)).toBe('')
    expect(formatClock(null, true)).toBe('')
  })
})
