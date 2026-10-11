import type { CongestionFeedbackRequest, FeedbackGrade } from '../../api/congestionFeedback'
import { isTransitLeg } from '../route/transitions'
import { segmentCongestionGradeForLeg } from '../route/segmentCongestion'
import type { Leg, Route } from '../route/types'

export interface FeedbackTarget {
  leg: Leg
  index: number
  // 추정 탑승 시각(ISO). 출발 시각을 모르면 없다.
  boardedAt?: string
}

export const FEEDBACK_OPTIONS: ReadonlyArray<{
  grade: FeedbackGrade
  label: string
  hint: string
}> = [
  { grade: 'RELAXED', label: '여유', hint: '앉을 자리 있음' },
  { grade: 'NORMAL', label: '보통', hint: '서서 갈 만함' },
  { grade: 'CONGESTED', label: '혼잡', hint: '몸이 닿을 정도' },
]

export function isFeedbackGrade(value: unknown): value is FeedbackGrade {
  return FEEDBACK_OPTIONS.some((option) => option.grade === value)
}

// 같은 길이면 먼저 탄 구간을 고른다.
function longest(legs: Array<{ leg: Leg; index: number }>) {
  return legs.reduce<{ leg: Leg; index: number } | null>(
    (best, item) => (!best || item.leg.minutes > best.leg.minutes ? item : best),
    null,
  )
}

/** 안내 경로에서 체감을 물을 구간 하나를 고른다. 지하철 우선, 없으면 버스, 둘 다 없으면 null이다. */
export function feedbackTarget(route: Route | null | undefined): FeedbackTarget | null {
  if (!route) return null
  const transit = route.legs
    .map((leg, index) => ({ leg, index }))
    .filter(({ leg }) => isTransitLeg(leg))
  const picked =
    longest(transit.filter(({ leg }) => leg.mode === 'subway')) ??
    longest(transit.filter(({ leg }) => leg.mode === 'bus'))
  if (!picked) return null
  const departedMs = route.departedAt ? new Date(route.departedAt).getTime() : NaN
  if (!Number.isFinite(departedMs)) return picked
  const beforeMinutes = route.legs
    .slice(0, picked.index)
    .reduce((total, leg) => total + leg.minutes + (leg.waitMinutes ?? 0), 0)
  const boardedMs = departedMs + (beforeMinutes + (picked.leg.waitMinutes ?? 0)) * 60_000
  return { ...picked, boardedAt: new Date(boardedMs).toISOString() }
}

function newFeedbackId() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function buildFeedbackRequest(
  target: FeedbackTarget,
  grade: FeedbackGrade,
  feedbackId: string = newFeedbackId(),
): CongestionFeedbackRequest {
  const { leg } = target
  return {
    feedbackId,
    mode: leg.mode === 'bus' ? 'bus' : 'subway',
    routeId: leg.routeId,
    fromStationId: leg.from?.id,
    fromName: leg.from?.name,
    toStationId: leg.to?.id,
    toName: leg.to?.name,
    boardedAt: target.boardedAt,
    reportedGrade: grade,
    predictedGrade: segmentCongestionGradeForLeg(leg),
  }
}
