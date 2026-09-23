import type { Place, Route } from '../route/types'
import type { GuidanceConditions, TrainArrival } from '../../api/guidance'
import { isTransitLeg } from '../route/transitions'

export type GuidanceLocationStatus =
  'idle' | 'waiting' | 'tracking' | 'denied' | 'no-position' | 'unsupported'

export interface GuidanceState {
  step: number
  train: string | null
  route: Route | null
  origin: Place | null
  destination: Place | null
  conditions?: GuidanceConditions
  selectedArrival?: TrainArrival | null
  completed: boolean
  locationStatus: GuidanceLocationStatus
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
  locationStatus: 'idle',
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
  | { type: 'set-step'; step: number }
  | { type: 'train'; time: string; arrival?: TrainArrival | null }
  | { type: 'replan'; route: Route }
  | { type: 'location-status'; status: GuidanceLocationStatus }
  | { type: 'location'; latitude: number; longitude: number; accuracy: number }

const MAX_GUIDANCE_ACCURACY_METERS = 15
const EARTH_RADIUS_METERS = 6_371_000

function distanceMeters(
  first: { latitude: number; longitude: number },
  second: { latitude: number; longitude: number },
) {
  const latitude = (second.latitude - first.latitude) * (Math.PI / 180)
  const longitude = (second.longitude - first.longitude) * (Math.PI / 180)
  const firstLatitude = first.latitude * (Math.PI / 180)
  const secondLatitude = second.latitude * (Math.PI / 180)
  const haversine =
    Math.sin(latitude / 2) ** 2 +
    Math.sin(longitude / 2) ** 2 * Math.cos(firstLatitude) * Math.cos(secondLatitude)
  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.sqrt(haversine))
}

function reachedWalkingEndpoint(
  state: GuidanceState,
  latitude: number,
  longitude: number,
  accuracy: number,
) {
  const leg = state.route?.legs[state.step]
  const endpoint = leg?.to
  if (
    state.completed ||
    !leg ||
    state.step >= (state.route?.legs.length || 0) - 1 ||
    (leg.mode !== 'walk' && leg.mode !== 'bike') ||
    !endpoint ||
    !Number.isFinite(endpoint.lat) ||
    !Number.isFinite(endpoint.lng) ||
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    !Number.isFinite(accuracy) ||
    accuracy < 0 ||
    accuracy > MAX_GUIDANCE_ACCURACY_METERS
  ) {
    return false
  }
  return (
    distanceMeters(
      { latitude, longitude },
      { latitude: endpoint.lat as number, longitude: endpoint.lng as number },
    ) +
      accuracy <=
    MAX_GUIDANCE_ACCURACY_METERS
  )
}

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
    case 'set-step':
      return state.route && !state.completed && Number.isInteger(action.step)
        ? action.step >= 0 && action.step < state.route.legs.length
          ? { ...state, step: action.step, train: null, selectedArrival: null }
          : state
        : state
    case 'train':
      return state.route && !state.completed
        ? { ...state, train: action.time, selectedArrival: action.arrival || null }
        : state
    case 'location-status':
      return state.locationStatus === action.status
        ? state
        : { ...state, locationStatus: action.status }
    case 'location':
      return reachedWalkingEndpoint(state, action.latitude, action.longitude, action.accuracy)
        ? { ...state, step: state.step + 1, train: null, selectedArrival: null }
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
