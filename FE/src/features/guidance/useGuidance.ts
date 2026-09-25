import { useCallback, useEffect, useReducer, useState } from 'react'
import type { Place, Route } from '../route/types'
import type { GuidanceConditions, TrainArrival } from '../../api/guidance'
import { LOCATION_MAX_AGE_MS } from './locationProgress'
import {
  guidanceReducer,
  initialGuidance,
  type GuidanceState,
  type GuidanceLocationStatus,
} from './guidanceReducer'

export const GUIDANCE_STORAGE_KEY = 'sugil:guidance'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage
  } catch {
    return null
  }
}

function removeStoredGuidance(currentStorage: Storage) {
  try {
    currentStorage.removeItem(GUIDANCE_STORAGE_KEY)
  } catch {
    // 저장소를 사용할 수 없어도 안내 화면은 계속 동작한다.
  }
}

function restoreGuidance(): GuidanceState {
  const currentStorage = storage()
  if (!currentStorage) return initialGuidance
  let raw: string | null
  try {
    raw = currentStorage.getItem(GUIDANCE_STORAGE_KEY)
  } catch {
    return initialGuidance
  }
  if (!raw) return initialGuidance
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    removeStoredGuidance(currentStorage)
    return initialGuidance
  }
  const route = isRecord(parsed) ? parsed.route : undefined
  const step = isRecord(parsed) ? parsed.step : undefined
  if (
    !isRecord(parsed) ||
    !isRecord(route) ||
    !Array.isArray(route.legs) ||
    route.legs.length === 0 ||
    !Number.isInteger(step) ||
    (step as number) < 0 ||
    (step as number) >= route.legs.length ||
    typeof parsed.completed !== 'boolean'
  ) {
    removeStoredGuidance(currentStorage)
    return initialGuidance
  }
  return {
    ...initialGuidance,
    ...(parsed as unknown as GuidanceState),
    locationStatus: 'idle',
    position: null,
    locationCandidateStep: undefined,
    locationCandidateCount: 0,
    transitAwayStep: undefined,
  }
}

export function useGuidance(trackingEnabled = false) {
  const [state, dispatch] = useReducer(guidanceReducer, undefined, restoreGuidance)
  const [trackingRetry, setTrackingRetry] = useState(0)
  const retryLocation = useCallback(() => setTrackingRetry((retry) => retry + 1), [])
  useEffect(() => {
    if (!trackingEnabled || !state.route || state.completed) {
      dispatch({ type: 'location-status', status: 'idle' })
      return
    }
    if (
      typeof navigator === 'undefined' ||
      !navigator.geolocation ||
      typeof navigator.geolocation.watchPosition !== 'function'
    ) {
      dispatch({ type: 'location-status', status: 'unsupported' })
      return
    }
    const geolocation = navigator.geolocation
    dispatch({ type: 'location-status', status: 'waiting' })
    let watchId: number | null = null
    let active = true
    let lastTimestamp = -Infinity
    let staleTimer: ReturnType<typeof setTimeout> | undefined
    try {
      watchId = geolocation.watchPosition(
        (position) => {
          if (!active) return
          const age = Date.now() - position.timestamp
          if (!Number.isFinite(position.timestamp) || age > LOCATION_MAX_AGE_MS || age < -1_000) {
            dispatch({ type: 'location-status', status: 'no-position' })
            return
          }
          // Cached/replayed fixes must not satisfy the two-observation arrival check.
          if (position.timestamp <= lastTimestamp) return
          lastTimestamp = position.timestamp
          clearTimeout(staleTimer)
          staleTimer = setTimeout(
            () => {
              if (active) dispatch({ type: 'location-status', status: 'no-position' })
            },
            Math.max(0, LOCATION_MAX_AGE_MS - age),
          )
          dispatch({
            type: 'location',
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy,
          })
        },
        (error) => {
          if (!active) return
          clearTimeout(staleTimer)
          dispatch({
            type: 'location-status',
            status: error.code === 1 ? 'denied' : 'no-position',
          })
        },
        { enableHighAccuracy: true, maximumAge: 5_000, timeout: 10_000 },
      )
    } catch {
      dispatch({ type: 'location-status', status: 'unsupported' })
    }
    return () => {
      active = false
      clearTimeout(staleTimer)
      if (watchId !== null) geolocation.clearWatch(watchId)
    }
  }, [state.completed, state.route, trackingEnabled, trackingRetry])
  useEffect(() => {
    if (!trackingEnabled || typeof navigator === 'undefined' || !navigator.permissions?.query)
      return
    let disposed = false
    let permission: PermissionStatus | null = null
    const onPermissionChange = () => {
      if (!disposed && permission?.state === 'granted') retryLocation()
    }
    void navigator.permissions
      .query({ name: 'geolocation' })
      .then((result) => {
        if (disposed) return
        permission = result
        result.addEventListener('change', onPermissionChange)
      })
      .catch(() => undefined)
    return () => {
      disposed = true
      permission?.removeEventListener('change', onPermissionChange)
    }
  }, [retryLocation, trackingEnabled])
  useEffect(() => {
    const currentStorage = storage()
    if (!currentStorage) return
    try {
      if (!state.route) {
        removeStoredGuidance(currentStorage)
        return
      }
      const {
        locationStatus: _locationStatus,
        position: _position,
        locationCandidateStep: _locationCandidateStep,
        locationCandidateCount: _locationCandidateCount,
        transitAwayStep: _transitAwayStep,
        ...persistedState
      } = state
      currentStorage.setItem(GUIDANCE_STORAGE_KEY, JSON.stringify(persistedState))
    } catch {
      // 저장소를 사용할 수 없어도 안내 화면은 계속 동작한다.
    }
  }, [state])
  const stop = useCallback(() => dispatch({ type: 'stop' }), [])
  return {
    ...state,
    active: Boolean(state.route && !state.completed),
    start: (
      route: Route,
      origin: Place | null,
      destination: Place | null,
      conditions?: GuidanceConditions,
    ) => dispatch({ type: 'start', route, origin, destination, conditions }),
    stop,
    previous: () => dispatch({ type: 'previous' }),
    next: () => dispatch({ type: 'next' }),
    setStep: (step: number) => dispatch({ type: 'set-step', step }),
    confirmStep: () => dispatch({ type: 'confirm-step' }),
    retryLocation,
    locationStatus: (state.locationStatus || 'idle') as GuidanceLocationStatus,
    setTrain: (time: string, arrival?: TrainArrival | null) =>
      dispatch({ type: 'train', time, arrival }),
    replan: (route: Route) => dispatch({ type: 'replan', route }),
  }
}
