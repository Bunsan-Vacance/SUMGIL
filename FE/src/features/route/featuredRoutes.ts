import type { Priority, Route } from './types'
import { congestionPredictionFor } from './selectors'

/** 결과 화면 추천 경로 선정·정렬. 가장 빠른 경로가 항상 첫 항목이다. */
export type Recommendation = 'fast' | 'calm'

export interface FeaturedRoute {
  route: Route
  recommendations: Recommendation[]
}

export function compareByTime(a: Route, b: Route, aIndex: number, bIndex: number) {
  return a.minutes - b.minutes || aIndex - bIndex
}

export function sortRoutes(routes: Route[], priority: Priority) {
  return routes
    .map((route, index) => ({
      route,
      index,
      prediction: congestionPredictionFor(route)?.congestionPercent,
    }))
    .sort((a, b) => {
      if (priority === 'fast') return compareByTime(a.route, b.route, a.index, b.index)
      if (a.prediction !== undefined && b.prediction !== undefined) {
        return a.prediction - b.prediction || compareByTime(a.route, b.route, a.index, b.index)
      }
      if (a.prediction !== undefined) return -1
      if (b.prediction !== undefined) return 1
      return compareByTime(a.route, b.route, a.index, b.index)
    })
    .map(({ route }) => route)
}

export function featuredRoutes(routes: Route[]): FeaturedRoute[] {
  if (!routes.length) return []
  const fastest = routes.reduce(
    (best, route, index) =>
      !best || compareByTime(route, best.route, index, best.index) < 0 ? { route, index } : best,
    undefined as { route: Route; index: number } | undefined,
  )
  const taggedCalm = routes.filter((route) => route.routeType === 'LOW_CONGESTION')
  const calmCandidates = taggedCalm.length
    ? taggedCalm
    : routes.filter((route) => congestionPredictionFor(route) !== undefined)
  const calm = calmCandidates.reduce<Route | undefined>((best, route) => {
    if (!best) return route
    if (taggedCalm.length) return compareByTime(route, best, 0, 0) < 0 ? route : best
    const routePercent = congestionPredictionFor(route)?.congestionPercent
    const bestPercent = congestionPredictionFor(best)?.congestionPercent
    if (routePercent === undefined || bestPercent === undefined) return best
    return routePercent < bestPercent ||
      (routePercent === bestPercent && route.minutes < best.minutes)
      ? route
      : best
  }, undefined)
  const result: FeaturedRoute[] = []
  if (fastest) result.push({ route: fastest.route, recommendations: ['fast'] })
  if (calm) {
    const existing = result.find((entry) => entry.route.id === calm.id)
    if (existing) existing.recommendations.push('calm')
    else result.push({ route: calm, recommendations: ['calm'] })
  }
  return result
}
