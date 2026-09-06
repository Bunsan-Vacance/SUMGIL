import { useEffect, useReducer, useRef } from 'react'
import { routeRepository } from '../../api/repositories'
import type { RouteRepository } from '../../api/contracts'
import { modes } from './constants'
import { getRoutes } from './selectors'
import { tripReducer, type TripState } from './tripReducer'
import type { Mode, Place, Priority, Route } from './types'

export function useTrip(initial: TripState, repository: RouteRepository = routeRepository) {
  const [state, dispatch] = useReducer(tripReducer, initial)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const search = async (destination: Place) => {
    request.current?.abort()
    const pending = new AbortController()
    request.current = pending
    dispatch({ type: 'search', destination })
    try {
      const candidates = await repository.search(
        { origin: state.origin, destination },
        pending.signal,
      )
      if (!pending.signal.aborted) dispatch({ type: 'loaded', routes: candidates })
    } catch {
      if (!pending.signal.aborted) dispatch({ type: 'failed' })
    }
  }
  return {
    ...state,
    visible: getRoutes(state.candidates, state.enabled, state.priority),
    search,
    setOrigin: (place: Place) => {
      if (place.id !== state.origin.id) request.current?.abort()
      dispatch({ type: 'origin', place })
    },
    setModes: (modes: Mode[]) => dispatch({ type: 'modes', modes }),
    setPriority: (priority: Priority) => dispatch({ type: 'priority', priority }),
    select: (id: string) => dispatch({ type: 'select', id }),
    acceptProposal: (route: Route) => dispatch({ type: 'proposal', route }),
    resetModes: () => dispatch({ type: 'modes', modes: modes.map((mode) => mode.id) }),
  }
}
