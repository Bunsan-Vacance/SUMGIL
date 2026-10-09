import { SEGMENT_CONGESTION_LEVELS } from '../route/segmentCongestion'
import type { SegmentCongestionGrade } from '../route/types'
import { HOURLY_NOW_INDEX } from './useStationHourlyCongestion'
import type { HourlyBar } from './useStationHourlyCongestion'

const rank = (grade: SegmentCongestionGrade) =>
  SEGMENT_CONGESTION_LEVELS.findIndex((level) => level.grade === grade)
const labelOf = (grade: SegmentCongestionGrade) =>
  SEGMENT_CONGESTION_LEVELS.find((level) => level.grade === grade)?.label ?? ''

/**
 * 지금 이후 막대의 변화를 한 문장으로 요약한다. 지금 등급이 없거나 이후 등급이 하나도 없으면 null이다.
 * 지금보다 낮은 등급과 높은 등급 중 먼저 나오는 쪽을 기준으로 한다.
 */
export function congestionAdvice(
  bars: HourlyBar[],
  nowIndex: number = HOURLY_NOW_INDEX,
): string | null {
  const current = bars[nowIndex]?.grade
  if (!current) return null
  const later = bars.slice(nowIndex + 1).filter((bar) => bar.grade !== null)
  if (!later.length) return null
  const currentRank = rank(current)
  for (const bar of later) {
    const barRank = rank(bar.grade as SegmentCongestionGrade)
    if (barRank < currentRank) {
      return `${bar.hour}시 이후 ${labelOf(bar.grade as SegmentCongestionGrade)} 수준으로 내려가요`
    }
    if (barRank > currentRank) {
      return `${bar.hour}시부터 ${labelOf(bar.grade as SegmentCongestionGrade)} 수준이에요`
    }
  }
  return `앞으로 ${later.length}시간 비슷해요`
}
