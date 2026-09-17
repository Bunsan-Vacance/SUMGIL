import type { Place, Route } from '../route/types'
import type { GuidanceConditions, TrainArrival } from '../../api/guidance'
import { isTransitLeg } from '../route/transitions'
export interface GuidanceState {
  step: number
  train: string | null
  route: Route | null
  origin: Place | null
  destination: Place | null
  conditions?: GuidanceConditions
  selectedArrival?: TrainArrival | null
  completed: boolean
}
export const initialGuidance: GuidanceState = {
  step: 0,
  train: null,
  route: null,
  origin: null,
  destination: null,
  conditions: { modes: [], priority: 'fast' },
  selectedArrival: null,
  completed: false,
}
export type GuidanceAction =
  | {
      type: 'start'
      route: Route
      origin: Place | null
      destination: Place | null
      conditions?: GuidanceConditions
    }
  | { type: 'stop' }
  | { type: 'previous' }
  | { type: 'next' }
  | { type: 'train'; time: string; arrival?: TrainArrival | null }
  | { type: 'replan'; route: Route }
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
            conditions: action.conditions || initialGuidance.conditions,
          }
        : initialGuidance
    }
    case 'stop':
      return initialGuidance
    case 'previous':
      if (!state.route) return state
      if (state.completed) return { ...state, completed: false, train: null, selectedArrival: null }
      return state.step > 0
        ? { ...state, step: state.step - 1, train: null, selectedArrival: null }
        : state
    case 'next':
      if (!state.route || state.completed) return state
      return state.step >= state.route.legs.length - 1
        ? { ...state, completed: true }
        : { ...state, step: state.step + 1, train: null, selectedArrival: null }
    case 'train':
      return state.route && !state.completed
        ? { ...state, train: action.time, selectedArrival: action.arrival || null }
        : state
    case 'replan': {
      if (!state.route || state.completed || !action.route.legs.length) return state
      const completedLegs = state.route.legs.slice(0, state.step)
      const legs = [...completedLegs, ...action.route.legs]
      const completedMinutes = completedLegs.reduce((total, leg) => total + leg.minutes, 0)
      const proposalAnchor = action.route.departedAt || state.route.departedAt
      const anchorMs = proposalAnchor ? new Date(proposalAnchor).getTime() : NaN
      const departedAt = Number.isFinite(anchorMs)
        ? new Date(anchorMs - completedMinutes * 60_000).toISOString()
        : undefined
      const routeGeometry = legs.flatMap((leg) => leg.geometry?.coordinates || [])
      const totalDistanceMeters = legs.every((leg) => leg.distanceMeters !== undefined)
        ? legs.reduce((total, leg) => total + (leg.distanceMeters || 0), 0)
        : undefined
      const walkingLegs = legs.filter(
        (leg) => leg.mode === 'walk' && !leg.transfer && !leg.transitionType,
      )
      const walk =
        walkingLegs.length > 0 && walkingLegs.every((leg) => leg.distanceMeters !== undefined)
          ? walkingLegs.reduce((total, leg) => total + (leg.distanceMeters || 0), 0)
          : undefined
      const transitRouteIds = legs
        .filter((leg) => isTransitLeg(leg) && leg.routeId)
        .map((leg) => leg.routeId as string)
      const routeTransitions = transitRouteIds
        .slice(1)
        .reduce((count, id, index) => count + (id !== transitRouteIds[index] ? 1 : 0), 0)
      const explicitTransfers = legs.filter(
        (leg) => leg.transfer || leg.transitionType === 'TRANSFER',
      ).length
      const transfers = Math.max(explicitTransfers, routeTransitions)
      return {
        ...state,
        route: {
          ...action.route,
          minutes: legs.reduce((total, leg) => total + leg.minutes, 0),
          transfers,
          modes: [...new Set(legs.filter((leg) => !leg.transfer).map((leg) => leg.mode))],
          congestionPrediction: undefined,
          legs,
          totalDistanceMeters,
          walk,
          geometry: routeGeometry.length
            ? { type: 'MultiLineString' as const, coordinates: routeGeometry }
            : undefined,
          departedAt,
        },
        train: null,
        selectedArrival: null,
        completed: false,
      }
    }
  }
}
