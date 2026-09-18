import { useCallback, useEffect, useReducer } from 'react'
import type { Place, Route } from '../route/types'
import type { GuidanceConditions, TrainArrival } from '../../api/guidance'
import { guidanceReducer, initialGuidance, type GuidanceState } from './guidanceReducer'

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
  return { ...initialGuidance, ...(parsed as unknown as GuidanceState) }
}

export function useGuidance() {
  const [state, dispatch] = useReducer(guidanceReducer, undefined, restoreGuidance)
  useEffect(() => {
    const currentStorage = storage()
    if (!currentStorage) return
    try {
      if (!state.route) {
        removeStoredGuidance(currentStorage)
        return
      }
      currentStorage.setItem(GUIDANCE_STORAGE_KEY, JSON.stringify(state))
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
    setTrain: (time: string, arrival?: TrainArrival | null) =>
      dispatch({ type: 'train', time, arrival }),
    replan: (route: Route) => dispatch({ type: 'replan', route }),
  }
}
