import { useEffect, useRef, useState } from 'react'
import { routeRepository } from '../../api/repositories'
import type { RouteRepository } from '../../api/contracts'
import {
  gradeIndex,
  pickSuggestion,
  shiftDeparture,
  SUGGESTION_OFFSETS_MIN,
  type DepartureSuggestion,
} from './departureSuggestion'
import { routeSignature } from './routeGrouping'
import type { Mode, Place, Priority, Route } from './types'

/** 입력이 멈춘 뒤 비교 조회를 시작하기까지의 지연(ms). */
const SEARCH_DELAY_MS = 600
const CACHE_LIMIT = 20

interface Input {
  base: Route | undefined
  origin: Place
  destination: Place | null
  modes: Mode[]
  priority: Priority
  departedAt: string | undefined
  enabled: boolean
  repository?: RouteRepository
}

/** useTrip.search와 같은 규칙: 도보는 항상 포함한다. */
function withWalk(selected: Mode[]) {
  return [...new Set<Mode>(['walk', ...selected])]
}

function placeKey(place: Place) {
  return `${place.id}@${place.lat ?? ''},${place.lng ?? ''}`
}

/**
 * 기준 경로가 혼잡할 때 +10·+20분 출발 결과를 읽기 전용으로 조회해 덜 붐비는 출발 시각 제안을 만든다.
 * 본 검색 상태(useTrip)에는 영향을 주지 않으며, 실패는 조용히 무시한다.
 */
export function useDepartureAlternatives({
  base,
  origin,
  destination,
  modes,
  priority,
  departedAt,
  enabled,
  repository = routeRepository,
}: Input): { suggestion: DepartureSuggestion | null } {
  const [suggestion, setSuggestion] = useState<DepartureSuggestion | null>(null)
  const cache = useRef(new Map<string, Route[]>())
  const latest = useRef({ base, origin, destination, modes, repository })
  latest.current = { base, origin, destination, modes, repository }

  // base 객체 참조 대신 판정에 쓰이는 값만 키로 삼아 재렌더마다 재조회하지 않는다.
  const baseIndex = base ? gradeIndex(base) : undefined
  const baseKey = base
    ? `${base.id}|${routeSignature(base) ?? ''}|${baseIndex ?? ''}|${base.minutes}`
    : ''
  const destinationKey = destination ? placeKey(destination) : ''
  const originKey = placeKey(origin)
  const modesKey = [...withWalk(modes)].sort().join(',')

  useEffect(() => {
    const { base: current, origin, destination, modes, repository } = latest.current
    if (
      !enabled ||
      !current ||
      !destination ||
      !departedAt ||
      baseIndex === undefined ||
      baseIndex === 0
    ) {
      setSuggestion(null)
      return
    }
    const targets = SUGGESTION_OFFSETS_MIN.flatMap((offsetMin) => {
      const shifted = shiftDeparture(departedAt, offsetMin)
      if (!shifted) return []
      const key = [originKey, destinationKey, modesKey, priority, shifted.iso].join('|')
      return [{ offsetMin, shifted, key }]
    })
    const store = cache.current
    const fromCache = () =>
      targets.flatMap(({ offsetMin, shifted, key }) => {
        const routes = store.get(key)
        return routes ? [{ offsetMin, clock: shifted.clock, routes }] : []
      })

    setSuggestion(null)
    if (targets.length === 0) return
    if (fromCache().length === targets.length) {
      setSuggestion(pickSuggestion(current, fromCache()))
      return
    }

    const controller = new AbortController()
    const timer = setTimeout(() => {
      const missing = targets.filter(({ key }) => !store.has(key))
      void Promise.all(
        missing.map(async ({ shifted, key }) => {
          try {
            const routes = await repository.search(
              {
                origin,
                destination,
                modes: withWalk(modes),
                priority,
                departedAt: shifted.iso,
              },
              controller.signal,
            )
            if (controller.signal.aborted) return
            store.delete(key)
            store.set(key, routes)
            while (store.size > CACHE_LIMIT) {
              const oldest = store.keys().next().value
              if (oldest === undefined) break
              store.delete(oldest)
            }
          } catch {
            // 한 오프셋이 실패해도 나머지로 제안한다. 에러는 노출하지 않는다.
          }
        }),
      ).then(() => {
        if (!controller.signal.aborted) setSuggestion(pickSuggestion(current, fromCache()))
      })
    }, SEARCH_DELAY_MS)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
    // 장소·수단·기준 경로는 키로 비교하고 실제 값은 latest ref로 읽는다.
  }, [enabled, baseKey, baseIndex, originKey, destinationKey, modesKey, priority, departedAt])

  return { suggestion }
}
