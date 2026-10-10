import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
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

function validDepartureTime(value: string) {
  return /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)
}

function todayInSeoul(date: Date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const valueOf = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value
  const year = valueOf('year')
  const month = valueOf('month')
  const day = valueOf('day')
  return year && month && day ? `${year}-${month}-${day}` : null
}

function departureAt(time: string, date = new Date()) {
  const today = todayInSeoul(date)
  return today ? new Date(`${today}T${time}:00+09:00`).toISOString() : date.toISOString()
}

export function useTrip(
  initial: TripState,
  repository: RouteRepository = routeRepository,
  initialDepartureTime?: string,
) {
  const [state, dispatch] = useReducer(tripReducer, initial)
  const [departureTime, setDeparture] = useState<string | null>(initialDepartureTime ?? null)
  // 마지막 검색에 실제로 쓴 출발 시각(ISO). URL 동기화가 effect 의존성으로 쓰도록 상태로 둔다.
  const [departedAt, setDepartedAt] = useState<string | undefined>(
    initial.candidates[0]?.departedAt,
  )
  const request = useRef<AbortController | null>(null)
  const departureOverride = useRef<string | null>(initialDepartureTime ?? null)
  const priorityRef = useRef(initial.priority)
  const lastDepartureAt = useRef(initial.candidates[0]?.departedAt)
  const visible = useMemo(
    () => getRoutes(state.candidates, state.enabled, state.priority),
    [state.candidates, state.enabled, state.priority],
  )
  useEffect(() => () => request.current?.abort(), [])
  const search = async (
    destination: Place,
    origin = state.origin,
    requestedModes = state.enabled,
    requestedDepartureAt?: string,
  ) => {
    request.current?.abort()
    const pending = new AbortController()
    request.current = pending
    const modes = withWalk(requestedModes)
    const selectedDeparture = departureOverride.current || departureTime
    const departedAt =
      requestedDepartureAt ||
      (selectedDeparture ? departureAt(selectedDeparture) : new Date().toISOString())
    lastDepartureAt.current = departedAt
    setDepartedAt(departedAt)
    dispatch({ type: 'search', origin, destination })
    try {
      const candidates = await repository.search(
        { origin, destination, modes, priority: priorityRef.current, departedAt },
        pending.signal,
      )
      if (!pending.signal.aborted) dispatch({ type: 'loaded', routes: candidates })
    } catch (error: unknown) {
      if (!pending.signal.aborted) {
        dispatch({
          type: 'failed',
          error: error instanceof RepositoryError ? error.message : undefined,
          code: error instanceof RepositoryError ? error.code : undefined,
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

  const setDepartureTime = (time: string) => {
    if (!validDepartureTime(time)) return false
    departureOverride.current = time
    setDeparture(time)
    if (state.destination) {
      void search(state.destination, state.origin, state.enabled, departureAt(time))
    }
    return true
  }

  const searchWithModes = (selected: Mode[]) => {
    const nextModes = withWalk(selected)
    if (sameModes(state.enabled, nextModes)) {
      if (state.destination) void search(state.destination, state.origin, nextModes)
      return
    }
    setModes(nextModes)
  }

  return {
    ...state,
    departureTime,
    departedAt,
    visible,
    search,
    setOrigin: (place: Place) => {
      if (place.id !== state.origin.id) request.current?.abort()
      dispatch({ type: 'origin', place })
    },
    setDestination: (place: Place) => {
      if (place.id !== state.destination?.id) request.current?.abort()
      dispatch({ type: 'destination', place })
    },
    swap: () => {
      request.current?.abort()
      dispatch({ type: 'swap' })
    },
    setModes,
    setDepartureTime,
    setPriority: (priority: Priority) => {
      if (priority === priorityRef.current) return
      priorityRef.current = priority
      dispatch({ type: 'priority', priority })
      if (state.destination && state.status !== 'idle') {
        void search(state.destination, state.origin, state.enabled, lastDepartureAt.current)
      }
    },
    select: (id: string) => dispatch({ type: 'select', id }),
    acceptProposal: (route: Route) => dispatch({ type: 'proposal', route }),
    resetModes: () => searchWithModes(modes.map((mode) => mode.id)),
    searchWalkOnly: () => searchWithModes(['walk']),
  }
}
