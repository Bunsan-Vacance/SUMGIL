import { calcEtaToRentalMinutes, findBoundary } from '../../api/reroute'
import type { Route } from '../route/types'

/** 환승·하차 몇 ms 전에 확인할지. */
export const LEAD_MS = 120_000
/** 대여소까지 남은 시간이 이 값(분)까지 줄어든 때 한 번 확인한다. */
export const HORIZON_MINUTES = 30
/** 이보다 긴 구간(분)은 중간 지점에서도 한 번 확인한다. */
export const LONG_LEG_MINUTES = 15
/** 체크포인트 최대 개수 — 넘으면 이른 것부터 남긴다. */
export const MAX_CHECKPOINTS = 8

const MINUTE_MS = 60_000

/** 현재 step이 시작된 시점을 0으로 본 체크포인트 지연(ms) 목록(오름차순·중복 제거, 모두 > 0).
 * - 경계(대여소로 걷는 leg) 전 각 leg의 끝 120초 전(환승·하차 직전)
 * - 대여소까지 남은 시간이 30분이 되는 시점
 * - 15분보다 긴 leg의 중간 지점(안전망)
 * 경계를 찾지 못하면 빈 배열이다. */
export function buildCheckpointDelays(route: Route | null, step: number): number[] {
  if (!route) return []
  const boundary = findBoundary(route, step)
  if (!boundary) return []
  const delays: number[] = []
  let elapsedMs = 0
  for (let i = step; i < boundary.legIndex; i += 1) {
    const leg = route.legs[i]
    const legMs = (leg.minutes + (leg.waitMinutes ?? 0)) * MINUTE_MS
    const endMs = elapsedMs + legMs
    delays.push(endMs - LEAD_MS)
    if (legMs > LONG_LEG_MINUTES * MINUTE_MS) delays.push(elapsedMs + legMs / 2)
    elapsedMs = endMs
  }
  const eta = calcEtaToRentalMinutes(route, step, boundary.legIndex)
  if (eta > HORIZON_MINUTES) delays.push((eta - HORIZON_MINUTES) * MINUTE_MS)
  const unique = [...new Set(delays.filter((d) => Number.isFinite(d) && d > 0))]
  return unique.sort((a, b) => a - b).slice(0, MAX_CHECKPOINTS)
}
