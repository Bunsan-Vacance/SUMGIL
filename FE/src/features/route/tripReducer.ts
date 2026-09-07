import type { Mode, Place, Priority, Route } from './types'
import { getRoutes } from './selectors'

export interface TripState {
  origin: Place
  destination: Place | null
  enabled: Mode[]
  priority: Priority
  candidates: Route[]
  selected: Route | null
  status: 'idle' | 'loading' | 'success' | 'error'
  error: string
}
export type TripAction =
  | { type: 'origin'; place: Place }
  | { type: 'search'; origin?: Place; destination: Place }
  | { type: 'swap' }
  | { type: 'loaded'; routes: Route[] }
  | { type: 'failed' }
  | { type: 'modes'; modes: Mode[] }
  | { type: 'priority'; priority: Priority }
  | { type: 'select'; id: string }
  | { type: 'proposal'; route: Route }
export function tripReducer(state: TripState, action: TripAction): TripState {
  switch (action.type) {
    case 'origin':
      if (state.origin.id === action.place.id) return state
      return {
        ...state,
        origin: action.place,
        candidates: [],
        selected: null,
        status: 'idle',
        error: '',
      }
    case 'search':
      return {
        ...state,
        origin: action.origin || state.origin,
        destination: action.destination,
        candidates: [],
        selected: null,
        status: 'loading',
        error: '',
      }
    case 'swap':
      if (!state.destination) return state
      return {
        ...state,
        origin: state.destination,
        destination: state.origin,
        candidates: [],
        selected: null,
        status: 'idle',
        error: '',
      }
    case 'loaded': {
      const available = getRoutes(action.routes, state.enabled, state.priority)
      return {
        ...state,
        candidates: action.routes,
        selected: available[0] || null,
        status: 'success',
        error: '',
      }
    }
    case 'failed':
      return {
        ...state,
        candidates: [],
        selected: null,
        status: 'error',
        error: '경로를 불러오지 못했어요.',
      }
    case 'modes': {
      if (!action.modes.length) return state
      const available = getRoutes(state.candidates, action.modes, state.priority)
      return {
        ...state,
        enabled: action.modes,
        selected:
          available.find((route) => route.id === state.selected?.id) || available[0] || null,
      }
    }
    case 'priority':
      return { ...state, priority: action.priority }
    case 'select': {
      const route = getRoutes(state.candidates, state.enabled, state.priority).find(
        (r) => r.id === action.id,
      )
      return route ? { ...state, selected: route } : state
    }
    case 'proposal':
      return {
        ...state,
        selected: action.route,
        candidates: [
          ...state.candidates.filter((route) => route.id !== action.route.id),
          action.route,
        ],
        enabled: [...new Set([...state.enabled, ...action.route.modes])],
      }
  }
}
