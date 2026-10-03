import type { TripState } from '../features/route/tripReducer'
import type { GuidanceState } from '../features/guidance/guidanceReducer'
import type { Screen } from './useNavigation'
import { isOpsViewEnabled } from './opsAccess'

export function resolveScreen(
  requested: Screen,
  trip: TripState,
  guidance: GuidanceState,
  opsEnabled = isOpsViewEnabled(),
): Screen {
  if (requested === 'ops') return opsEnabled ? 'ops' : 'home'
  if (requested === 'home' || requested === 'browse' || requested === 'search') return requested
  if (requested === 'guide' || requested === 'arrival') {
    const hasSession =
      Boolean(guidance.route?.legs.length) &&
      guidance.step >= 0 &&
      guidance.step < (guidance.route?.legs.length ?? 0)
    if (hasSession) {
      if (requested === 'arrival' && !guidance.completed) return 'guide'
      if (requested === 'guide' && guidance.completed) return 'arrival'
      return requested
    }
  }
  if (!trip.destination || trip.status === 'idle') return 'home'
  const selected = trip.status === 'success' && trip.selected?.legs.length ? trip.selected : null
  if (requested === 'detail' && !selected) return 'results'
  if (requested === 'guide' || requested === 'arrival') {
    return selected ? 'detail' : 'results'
  }
  return requested
}
