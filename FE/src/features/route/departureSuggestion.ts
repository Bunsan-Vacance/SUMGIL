import type { Route, SegmentCongestionGrade } from './types'
import { routeSignature } from './routeGrouping'
import { SEGMENT_CONGESTION_LEVELS, segmentCongestionPresentation } from './segmentCongestion'
import {
  clockTime,
  congestionPredictionFor,
  congestionPredictionPresentation,
  parseDeparture,
} from './selectors'

/** 덜 붐비는 출발 시각을 찾아볼 오프셋(분). 늦게 출발하는 방향만 본다. */
export const SUGGESTION_OFFSETS_MIN = [10, 20] as const

export interface DepartureSuggestion {
  offsetMin: number
  clock: string
  fromGrade: SegmentCongestionGrade
  toGrade: SegmentCongestionGrade
  /** 도착 시각 변화(분). 양수면 늦게 도착. */
  arrivalDeltaMin: number
}

function seoulDate(value: Date) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(value)
}

/** 출발 시각을 offsetMin분 미룬다. 서울 기준 날짜가 바뀌거나 해석할 수 없으면 null. */
export function shiftDeparture(
  departedAt: string,
  offsetMin: number,
): { iso: string; clock: string } | null {
  const base = parseDeparture(departedAt)
  if (!base) return null
  const shifted = new Date(base.getTime() + offsetMin * 60_000)
  if (seoulDate(shifted) !== seoulDate(base)) return null
  const clock = clockTime(shifted.toISOString())
  return clock ? { iso: shifted.toISOString(), clock } : null
}

/** 경로의 예측 혼잡 등급 인덱스(SEGMENT_CONGESTION_LEVELS 기준, 낮을수록 여유). 근거 없으면 undefined. */
export function gradeIndex(route: Route): number | undefined {
  const prediction = congestionPredictionFor(route)
  if (!prediction) return undefined
  const grade = congestionPredictionPresentation(prediction, route.legs)?.grade
  if (!grade) return undefined
  const index = SEGMENT_CONGESTION_LEVELS.findIndex((level) => level.grade === grade)
  return index >= 0 ? index : undefined
}

/** 기준 경로와 같은 경로(구간 서명 동일)가 더 늦은 출발에서 한 등급 이상 여유로우면 제안 1개를 고른다. */
export function pickSuggestion(
  base: Route,
  alternatives: Array<{ offsetMin: number; clock: string; routes: Route[] }>,
): DepartureSuggestion | null {
  const baseIndex = gradeIndex(base)
  if (baseIndex === undefined || baseIndex === 0) return null
  const signature = routeSignature(base)
  if (!signature) return null

  let best: { alt: (typeof alternatives)[number]; route: Route; index: number } | undefined
  for (const alt of alternatives) {
    let candidate: { route: Route; index: number } | undefined
    for (const route of alt.routes) {
      if (routeSignature(route) !== signature) continue
      const index = gradeIndex(route)
      if (index === undefined) continue
      if (!candidate || index < candidate.index) candidate = { route, index }
    }
    if (!candidate || candidate.index >= baseIndex) continue
    const gain = baseIndex - candidate.index
    const bestGain = best ? baseIndex - best.index : 0
    if (!best || gain > bestGain || (gain === bestGain && alt.offsetMin < best.alt.offsetMin)) {
      best = { alt, ...candidate }
    }
  }
  if (!best) return null
  return {
    offsetMin: best.alt.offsetMin,
    clock: best.alt.clock,
    fromGrade: SEGMENT_CONGESTION_LEVELS[baseIndex].grade,
    toGrade: SEGMENT_CONGESTION_LEVELS[best.index].grade,
    arrivalDeltaMin: best.alt.offsetMin + Math.round(best.route.minutes - base.minutes),
  }
}

/** 칩 표시용 파생 값. 등급 단어·색은 구간 혼잡 표현을 따른다. */
export function suggestionView(s: DepartureSuggestion) {
  const from = segmentCongestionPresentation(s.fromGrade)
  const to = segmentCongestionPresentation(s.toGrade)
  const fromLabel = from?.label ?? ''
  const toLabel = to?.label ?? ''
  const d = s.arrivalDeltaMin
  const arrivalText = d > 0 ? `도착 +${d}분` : d < 0 ? `도착 −${-d}분` : '도착 시각 비슷'
  const arrivalAria =
    d > 0 ? `도착 ${d}분 늦어짐` : d < 0 ? `도착 ${-d}분 빨라짐` : '도착 시각 비슷'
  return {
    title: `${s.offsetMin}분 늦게 출발하면`,
    fromLabel,
    fromColor: from?.color ?? 'currentColor',
    toLabel,
    toColor: to?.color ?? 'currentColor',
    detail: `${s.clock} 출발 · ${arrivalText} · 예측 기준`,
    ariaLabel: `${s.offsetMin}분 늦게 ${s.clock}에 출발하면 ${fromLabel}에서 ${toLabel}, ${arrivalAria}, 예측 기준. 이 시각으로 다시 찾기`,
  }
}
