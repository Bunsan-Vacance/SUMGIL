import { useEffect, useState } from 'react'
import { congestionRepository } from '../../api/congestion'
import type { Leg } from './types'

export interface LegCongestion {
  status: 'loading' | 'ready' | 'unavailable'
  level?: number
}

function targetId(leg: Leg) {
  return leg.mode === 'subway' ? leg.from?.id : undefined
}

export function useRouteCongestion(legs: Leg[], departureTime?: string): LegCongestion[] {
  const repository = congestionRepository
  const targets = legs.map((leg) => targetId(leg))
  const targetKey = targets.join('|')
  const requestKey = `${targetKey}|${departureTime || ''}`
  const [states, setStates] = useState<LegCongestion[]>([])
  const [stateKey, setStateKey] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const initial = targets.map((id) => ({
      status: id && repository ? ('loading' as const) : ('unavailable' as const),
    }))
    setStateKey(requestKey)
    setStates(initial)
    if (!repository || !targets.some(Boolean)) return () => controller.abort()

    Promise.all(
      targets.map((id) =>
        id
          ? repository.get('STATION', id, departureTime, controller.signal).catch(() => undefined)
          : Promise.resolve(undefined),
      ),
    ).then((results) => {
      if (controller.signal.aborted) return
      setStates(
        results.map((result) =>
          result
            ? { status: 'ready' as const, level: result.level }
            : { status: 'unavailable' as const },
        ),
      )
    })

    return () => controller.abort()
  }, [requestKey])

  return stateKey === requestKey && states.length === legs.length
    ? states
    : legs.map((leg) => ({
        status: targetId(leg) && repository ? ('loading' as const) : ('unavailable' as const),
      }))
}
