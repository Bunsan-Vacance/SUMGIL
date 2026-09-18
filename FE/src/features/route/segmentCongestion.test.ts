import { describe, expect, it } from 'vitest'
import { segmentCongestionGradeForLevel } from './segmentCongestion'

describe('혼잡 level 구간 등급 변환', () => {
  it('경계값을 포함해 여유·보통·혼잡·포화로 변환한다', () => {
    expect([39.9, 40, 69.9, 70, 99.9, 100].map(segmentCongestionGradeForLevel)).toEqual([
      'RELAXED',
      'NORMAL',
      'NORMAL',
      'CONGESTED',
      'CONGESTED',
      'SATURATED',
    ])
  })

  it('조회되지 않은 level은 등급을 만들지 않는다', () => {
    expect(segmentCongestionGradeForLevel()).toBeUndefined()
    expect(segmentCongestionGradeForLevel(Number.NaN)).toBeUndefined()
    expect(segmentCongestionGradeForLevel(120)).toBe('SATURATED')
  })
})
