import { useCallback, useReducer } from 'react'
import type { Place, Route } from '../route/types'
import type { GuidanceConditions, TrainArrival } from '../../api/guidance'
import { guidanceReducer, initialGuidance } from './guidanceReducer'

export function useGuidance() {
  const [state, dispatch] = useReducer(guidanceReducer, initialGuidance)
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
