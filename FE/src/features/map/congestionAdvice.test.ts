import { describe, expect, it } from 'vitest'
import type { SegmentCongestionGrade } from '../route/types'
import { congestionAdvice } from './congestionAdvice'
import type { HourlyBar } from './useStationHourlyCongestion'

const bars = (grades: Array<SegmentCongestionGrade | null>): HourlyBar[] =>
  grades.map((grade, index) => ({
    departureTime: `2026-10-09T${String(17 + index).padStart(2, '0')}:00:00`,
    hour: 17 + index,
    label: index === 1 ? '지금' : `${17 + index}시`,
    level: grade ? 50 : null,
    grade,
  }))

describe('혼잡도 변화 요약', () => {
  it('지금보다 낮은 등급이 처음 나오는 시각을 알려 준다', () => {
    expect(
      congestionAdvice(bars(['CONGESTED', 'CONGESTED', 'CONGESTED', 'NORMAL', 'RELAXED', null])),
    ).toBe('20시 이후 보통 수준으로 내려가요')
  })

  it('지금보다 높은 등급이 먼저 나오면 그 시각을 알려 준다', () => {
    expect(congestionAdvice(bars(['NORMAL', 'NORMAL', 'NORMAL', 'CONGESTED', null, null]))).toBe(
      '20시부터 혼잡 수준이에요',
    )
  })

  it('먼저 나오는 쪽을 기준으로 한다', () => {
    expect(congestionAdvice(bars(['NORMAL', 'NORMAL', 'CONGESTED', 'RELAXED', null, null]))).toBe(
      '19시부터 혼잡 수준이에요',
    )
    expect(
      congestionAdvice(bars(['NORMAL', 'CONGESTED', 'RELAXED', 'SATURATED', null, null])),
    ).toBe('19시 이후 여유 수준으로 내려가요')
  })

  it('이후 등급이 모두 같으면 비슷하다고 알려 준다', () => {
    expect(congestionAdvice(bars(['NORMAL', 'NORMAL', 'NORMAL', null, 'NORMAL', 'NORMAL']))).toBe(
      '앞으로 3시간 비슷해요',
    )
  })

  it('지금 등급이 없거나 이후 등급이 하나도 없으면 null이다', () => {
    expect(congestionAdvice(bars(['NORMAL', null, 'NORMAL', 'NORMAL', null, null]))).toBeNull()
    expect(congestionAdvice(bars(['NORMAL', 'NORMAL', null, null, null, null]))).toBeNull()
    expect(congestionAdvice([])).toBeNull()
  })
})
