import type { TripState } from '../features/route/tripReducer'
import { parseRouteQuery } from './routeQuery'
import { parseHash } from './useNavigation'

/**
 * 결과·상세 화면의 해시에서 경로 검색 조건을 복원한다.
 * 첫 렌더부터 결과 화면이 유지되도록 status를 loading으로 두고, 실제 검색은 호출 측이 시작한다.
 * 해시가 결과·상세가 아니거나 쿼리가 잘못되면 null이다.
 */
export function restoredTripFor(
  hash: string,
  base: TripState,
): { trip: TripState; departureAt?: string } | null {
  const { screen, query } = parseHash(hash)
  if (screen !== 'results' && screen !== 'detail') return null
  const parsed = parseRouteQuery(query)
  if (!parsed) return null
  const trip: TripState = {
    ...base,
    origin: parsed.origin,
    destination: parsed.destination,
    status: 'loading',
  }
  return parsed.departureAt ? { trip, departureAt: parsed.departureAt } : { trip }
}
