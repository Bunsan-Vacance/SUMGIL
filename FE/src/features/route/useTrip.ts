import { useEffect, useReducer, useRef } from 'react'
import { routeRepository } from '../../api/repositories'
import { RepositoryError } from '../../api/errors'
import type { RouteRepository } from '../../api/contracts'
import { modes } from './constants'
import { getRoutes } from './selectors'
import { tripReducer, type TripState } from './tripReducer'
import type { Mode, Place, Priority, Route } from './types'

function withWalk(selected: Mode[]) {
  return [...new Set<Mode>(['walk', ...selected])]
}

function sameModes(first: Mode[], second: Mode[]) {
  return first.length === second.length && first.every((mode) => second.includes(mode))
}

export function useTrip(initial: TripState, repository: RouteRepository = routeRepository) {
  const [state, dispatch] = useReducer(tripReducer, initial)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const search = async (
    destination: Place,
    origin = state.origin,
    requestedModes = state.enabled,
  ) => {
    request.current?.abort()
    const pending = new AbortController()
    request.current = pending
    const modes = withWalk(requestedModes)
    const departedAt = new Date().toISOString()
    dispatch({ type: 'search', origin, destination })
    try {
      const candidates = await repository.search(
        { origin, destination, modes, priority: state.priority, departedAt },
        pending.signal,
      )
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
  const setModes = (selected: Mode[]) => {
    const nextModes = withWalk(selected)
    if (sameModes(state.enabled, nextModes)) return
    dispatch({ type: 'modes', modes: nextModes })
    if (state.destination && state.status !== 'idle') {
      void search(state.destination, state.origin, nextModes)
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
    setModes,
    setPriority: (priority: Priority) => dispatch({ type: 'priority', priority }),
    select: (id: string) => dispatch({ type: 'select', id }),
    acceptProposal: (route: Route) => dispatch({ type: 'proposal', route }),
    resetModes: () => setModes(modes.map((mode) => mode.id)),
  }
}
