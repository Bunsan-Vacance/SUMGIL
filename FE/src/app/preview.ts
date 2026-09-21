import { bikeProposal, places, routes } from '../api/mock/fixtures'
import { modes } from '../features/route/constants'
import type { TripState } from '../features/route/tripReducer'

export const emptyOrigin = {
  id: 'empty-origin',
  name: '',
  address: '',
  kind: '장소',
} as const

// A route becomes available only after a completed search.
export const previewTrip: TripState = {
  origin: emptyOrigin,
  destination: null,
  candidates: [],
  selected: null,
  enabled: modes.map((mode) => mode.id),
  priority: 'fast',
  status: 'idle',
  error: '',
  errorCode: null,
}

export function isCongestionPreview(search: string, isDev = import.meta.env.DEV) {
  return isDev && new URLSearchParams(search).get('preview') === 'congestion'
}

export function previewTripFor(search: string, isDev = import.meta.env.DEV): TripState {
  if (!isCongestionPreview(search, isDev)) return previewTrip
  const departedAt = new Date().toISOString()
  const previewRoutes = routes.map((route) => ({ ...route, departedAt }))
  return {
    ...previewTrip,
    origin: places[0],
    destination: places[1],
    candidates: previewRoutes,
    selected: previewRoutes[0],
    status: 'success',
  }
}

export const previewProposal = bikeProposal
