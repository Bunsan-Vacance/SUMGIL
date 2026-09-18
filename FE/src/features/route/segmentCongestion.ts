import type { Leg, SegmentCongestionGrade } from './types'

export const SEGMENT_CONGESTION_LEVELS = [
  { grade: 'RELAXED', label: '여유', color: '#1d4ed8' },
  { grade: 'NORMAL', label: '보통', color: '#15803d' },
  { grade: 'CONGESTED', label: '혼잡', color: '#b91c1c' },
  { grade: 'SATURATED', label: '포화', color: '#7e22ce' },
] as const satisfies ReadonlyArray<{
  grade: SegmentCongestionGrade
  label: string
  color: string
}>

export const SEGMENT_CONGESTION_PREVIEW_LEVELS = [20, 50, 80, 110] as const

export function segmentCongestionLevelForIndex(index: number) {
  return SEGMENT_CONGESTION_PREVIEW_LEVELS[index % SEGMENT_CONGESTION_PREVIEW_LEVELS.length]
}

const levels = Object.fromEntries(
  SEGMENT_CONGESTION_LEVELS.map((level) => [level.grade, level]),
) as Record<SegmentCongestionGrade, (typeof SEGMENT_CONGESTION_LEVELS)[number]>

export function segmentCongestionPresentation(grade?: SegmentCongestionGrade) {
  return grade ? levels[grade] : undefined
}

export function segmentCongestionGradeForLevel(level?: number): SegmentCongestionGrade | undefined {
  if (level === undefined || !Number.isFinite(level)) return undefined
  if (level < 40) return 'RELAXED'
  if (level < 70) return 'NORMAL'
  if (level < 100) return 'CONGESTED'
  return 'SATURATED'
}

export function withSegmentCongestionPreview(legs: Leg[]) {
  let transitIndex = 0
  return legs.map((leg) => {
    if ((leg.mode !== 'subway' && leg.mode !== 'bus') || leg.transfer) return leg
    const level = segmentCongestionLevelForIndex(transitIndex++)
    if (leg.segmentCongestionGrade) return leg
    const grade = segmentCongestionGradeForLevel(level)
    return grade ? { ...leg, segmentCongestionGrade: grade } : leg
  })
}
