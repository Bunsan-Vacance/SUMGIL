import type { SegmentCongestionGrade } from './types'

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

/** 등급 경계(%). 여유<40≤보통<70≤혼잡<100≤포화. 등급 판정과 범례 라벨이 같은 값을 쓴다. */
export const SEGMENT_CONGESTION_THRESHOLDS = [40, 70, 100] as const

const levels = Object.fromEntries(
  SEGMENT_CONGESTION_LEVELS.map((level) => [level.grade, level]),
) as Record<SegmentCongestionGrade, (typeof SEGMENT_CONGESTION_LEVELS)[number]>

export function segmentCongestionPresentation(grade?: SegmentCongestionGrade) {
  return grade ? levels[grade] : undefined
}

export function segmentCongestionGradeForLevel(level?: number): SegmentCongestionGrade | undefined {
  if (level === undefined || !Number.isFinite(level)) return undefined
  const [normalMin, congestedMin, saturatedMin] = SEGMENT_CONGESTION_THRESHOLDS
  if (level < normalMin) return 'RELAXED'
  if (level < congestedMin) return 'NORMAL'
  if (level < saturatedMin) return 'CONGESTED'
  return 'SATURATED'
}

export function segmentCongestionGradeForLeg(leg: {
  segmentCongestionGrade?: SegmentCongestionGrade | null
  segmentCongestionLevel?: number
}) {
  return leg.segmentCongestionGrade ?? segmentCongestionGradeForLevel(leg.segmentCongestionLevel)
}
