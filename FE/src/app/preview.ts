import { bikeProposal, places, routes } from '../api/mock/fixtures'
import { routeSearchMockResponse } from '../api/mock/routeResponses'
import { mapRouteApiResponse } from '../api/routeMapper'
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
  const scenario = new URLSearchParams(search).get('preview')
  if (isDev && (scenario === 'bike' || scenario === 'short')) {
    const departedAt = new Date().toISOString()
    const candidates = mapRouteApiResponse(routeSearchMockResponse, departedAt)
    const selected =
      scenario === 'bike'
        ? candidates.find((route) => route.legs.some((leg) => leg.mode === 'bike'))!
        : candidates[0]
    const from = selected.legs[0].from!
    const to = selected.legs.at(-1)!.to!
    return {
      ...previewTrip,
      origin: {
        ...from,
        id: from.id || 'preview-origin',
        name: from.name || '출발',
        address: '',
        kind: '장소',
      },
      destination: {
        ...to,
        id: to.id || 'preview-destination',
        name: to.name || '도착',
        address: '',
        kind: '장소',
      },
      candidates,
      selected,
      status: 'success',
    }
  }
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
