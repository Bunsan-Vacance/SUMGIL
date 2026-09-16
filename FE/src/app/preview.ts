import { places, bikeProposal } from '../api/mock/fixtures'
import { modes } from '../features/route/constants'
import type { TripState } from '../features/route/tripReducer'
// A route becomes available only after a completed search.
export const previewTrip: TripState = {
  origin: places[0],
  destination: null,
  candidates: [],
  selected: null,
  enabled: modes.map((mode) => mode.id),
  priority: 'fast',
  status: 'idle',
  error: '',
}
export const previewProposal = bikeProposal
