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

/** 제안 기준 경로. kind는 추천 경로 배지 종류(둘을 겸하면 both). */
export type SuggestionKind = 'fast' | 'calm' | 'both'
export interface SuggestionBase {
  kind: SuggestionKind
  route: Route
}
export interface RouteSuggestion {
  kind: SuggestionKind
  routeId: string
  suggestion: DepartureSuggestion
}

const NO_SUGGESTIONS: RouteSuggestion[] = []

interface Input {
  bases: SuggestionBase[]
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
  bases,
  origin,
  destination,
  modes,
  priority,
  departedAt,
  enabled,
  repository = routeRepository,
}: Input): { suggestions: RouteSuggestion[] } {
  const [suggestions, setSuggestions] = useState<RouteSuggestion[]>(NO_SUGGESTIONS)
  const cache = useRef(new Map<string, Route[]>())
  const latest = useRef({ bases, origin, destination, modes, repository })
  latest.current = { bases, origin, destination, modes, repository }

  // base 객체 참조 대신 판정에 쓰이는 값만 키로 삼아 재렌더마다 재조회하지 않는다.
  const baseKey = bases
    .map(({ kind, route }) =>
      [kind, route.id, routeSignature(route) ?? '', gradeIndex(route) ?? '', route.minutes].join(
        ':',
      ),
    )
    .join('|')
  const needsComparison = bases.some(({ route }) => {
    const index = gradeIndex(route)
    return index !== undefined && index > 0
  })
  const destinationKey = destination ? placeKey(destination) : ''
  const originKey = placeKey(origin)
  const modesKey = [...withWalk(modes)].sort().join(',')

  useEffect(() => {
    const { bases: currentBases, origin, destination, modes, repository } = latest.current
    if (!enabled || !destination || !departedAt || !needsComparison) {
      setSuggestions(NO_SUGGESTIONS)
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

    const pick = () =>
      currentBases.flatMap(({ kind, route }) => {
        const suggestion = pickSuggestion(route, fromCache())
        return suggestion ? [{ kind, routeId: route.id, suggestion }] : []
      })

    setSuggestions(NO_SUGGESTIONS)
    if (targets.length === 0) return
    if (fromCache().length === targets.length) {
      setSuggestions(pick())
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
        if (!controller.signal.aborted) setSuggestions(pick())
      })
    }, SEARCH_DELAY_MS)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
    // 장소·수단·기준 경로는 키로 비교하고 실제 값은 latest ref로 읽는다.
  }, [enabled, baseKey, needsComparison, originKey, destinationKey, modesKey, priority, departedAt])

  return { suggestions }
}
