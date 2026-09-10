import { useEffect, useReducer, useRef } from 'react'
import { routeRepository } from '../../api/repositories'
import { RepositoryError } from '../../api/errors'
import type { RouteRepository } from '../../api/contracts'
import { modes } from './constants'
import { getRoutes } from './selectors'
import { tripReducer, type TripState } from './tripReducer'
import type { Mode, Place, Priority, Route } from './types'

export function useTrip(initial: TripState, repository: RouteRepository = routeRepository) {
  const [state, dispatch] = useReducer(tripReducer, initial)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const search = async (destination: Place, origin = state.origin) => {
    request.current?.abort()
    const pending = new AbortController()
    request.current = pending
    dispatch({ type: 'search', origin, destination })
    try {
      const candidates = await repository.search({ origin, destination }, pending.signal)
      if (!pending.signal.aborted) dispatch({ type: 'loaded', routes: candidates })
    } catch (error: unknown) {
      if (!pending.signal.aborted) {
        dispatch({
          type: 'failed',
          error: error instanceof RepositoryError ? error.message : undefined,
        })
      }
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
    swap: () => {
      request.current?.abort()
      dispatch({ type: 'swap' })
    },
    setModes: (modes: Mode[]) => dispatch({ type: 'modes', modes }),
    setPriority: (priority: Priority) => dispatch({ type: 'priority', priority }),
    select: (id: string) => dispatch({ type: 'select', id }),
    acceptProposal: (route: Route) => dispatch({ type: 'proposal', route }),
    resetModes: () => dispatch({ type: 'modes', modes: modes.map((mode) => mode.id) }),
  }
}
