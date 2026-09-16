import type { Place, Route } from '../route/types'
export interface GuidanceState {
  step: number
  train: string | null
  route: Route | null
  origin: Place | null
  destination: Place | null
  completed: boolean
}
export const initialGuidance: GuidanceState = {
  step: 0,
  train: null,
  route: null,
  origin: null,
  destination: null,
  completed: false,
}
export type GuidanceAction =
  | { type: 'start'; route: Route; origin: Place | null; destination: Place | null }
  | { type: 'stop' }
  | { type: 'next' }
  | { type: 'train'; time: string }
export function guidanceReducer(state: GuidanceState, action: GuidanceAction): GuidanceState {
  switch (action.type) {
    case 'start': {
      const sameActiveTrip =
        !state.completed &&
        state.route === action.route &&
        state.origin?.id === action.origin?.id &&
        state.destination?.id === action.destination?.id
      if (sameActiveTrip) return state
      return action.route.legs.length
        ? {
            ...initialGuidance,
            route: action.route,
            origin: action.origin,
            destination: action.destination,
          }
        : initialGuidance
    }
    case 'stop':
      return initialGuidance
    case 'next':
      if (!state.route || state.completed) return state
      return state.step >= state.route.legs.length - 1
        ? { ...state, completed: true }
        : { ...state, step: state.step + 1 }
    case 'train':
      return state.route && !state.completed ? { ...state, train: action.time } : state
  }
}
