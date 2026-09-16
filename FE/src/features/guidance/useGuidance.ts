import { useCallback, useReducer } from 'react'
import type { Place, Route } from '../route/types'
import { guidanceReducer, initialGuidance } from './guidanceReducer'

export function useGuidance() {
  const [state, dispatch] = useReducer(guidanceReducer, initialGuidance)
  const stop = useCallback(() => dispatch({ type: 'stop' }), [])
  return {
    ...state,
    active: Boolean(state.route && !state.completed),
    start: (route: Route, origin: Place | null, destination: Place | null) =>
      dispatch({ type: 'start', route, origin, destination }),
    stop,
    next: () => dispatch({ type: 'next' }),
    setTrain: (time: string) => dispatch({ type: 'train', time }),
  }
}
