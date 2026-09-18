import { describe, expect, it } from 'vitest'
import {
  segmentCongestionGradeForLevel,
  segmentCongestionLevelForIndex,
  withSegmentCongestionPreview,
} from './segmentCongestion'

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
  })

  it('지하철·버스 구간에만 네 단계 mock을 순서대로 주입한다', () => {
    const legs = withSegmentCongestionPreview([
      { mode: 'walk', title: 'A → B', note: '도보', minutes: 1 },
      { mode: 'subway', title: 'B → C', note: '지하철', minutes: 1 },
      { mode: 'bus', title: 'C → D', note: '버스', minutes: 1 },
      { mode: 'walk', transfer: true, title: '환승', note: '환승', minutes: 1 },
      { mode: 'bike', title: 'D → E', note: '자전거', minutes: 1 },
    ])

    expect(legs.map((leg) => leg.segmentCongestionGrade)).toEqual([
      undefined,
      segmentCongestionGradeForLevel(segmentCongestionLevelForIndex(0)),
      segmentCongestionGradeForLevel(segmentCongestionLevelForIndex(1)),
      undefined,
      undefined,
    ])
  })
})
