import { isRecord, isStoredPlace, readStoredList, writeStoredList } from './placeStorage'
import type { Place } from './types'

export interface RecentRoute {
  id: string
  /** 현재 위치 출발은 좌표가 매번 달라 장소로 저장하지 않고 null로 둔다. */
  origin: Place | null
  destination: Place
  searchedAt: string
  pinned: boolean
}

export const RECENT_ROUTES_STORAGE_KEY = 'sugil:recent-routes'
const RECENT_ROUTES_LIMIT = 10

function isCurrentLocation(place: Place): boolean {
  return place.kind === '현재 위치' || place.id.startsWith('current-location:')
}

export function recentRouteId(origin: Place | null, destination: Place): string {
  return `${origin?.id ?? 'current-location'}>${destination.id}`
}

/** 고정 항목을 먼저, 그 안에서 검색 시각 최신순으로 정렬한 새 배열을 돌려준다. */
export function sortRecentRoutes(list: RecentRoute[]): RecentRoute[] {
  return [...list].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    return Date.parse(b.searchedAt) - Date.parse(a.searchedAt)
  })
}

function normalizeRecentRoutes(value: unknown): RecentRoute[] {
  if (!Array.isArray(value)) return []
  const ids = new Set<string>()
  const items: RecentRoute[] = []
  for (const item of value) {
    if (!isRecord(item)) continue
    const { origin, destination, searchedAt, pinned, id } = item
    if (origin !== null && !isStoredPlace(origin)) continue
    if (!isStoredPlace(destination)) continue
    if (typeof searchedAt !== 'string' || !Number.isFinite(Date.parse(searchedAt))) continue
    if (typeof pinned !== 'boolean') continue
    if (id !== recentRouteId(origin, destination) || ids.has(id)) continue
    ids.add(id)
    items.push({ id, origin, destination, searchedAt, pinned })
  }
  return sortRecentRoutes(items)
}

export function loadRecentRoutes(): RecentRoute[] {
  return normalizeRecentRoutes(readStoredList(RECENT_ROUTES_STORAGE_KEY))
}

/** 한도를 넘으면 고정되지 않은 가장 오래된 항목부터 제거한다. 고정 항목은 제거하지 않는다. */
function trimToLimit(list: RecentRoute[]): RecentRoute[] {
  const sorted = sortRecentRoutes(list)
  while (sorted.length > RECENT_ROUTES_LIMIT) {
    let index = -1
    for (let i = sorted.length - 1; i >= 0; i -= 1) {
      if (!sorted[i].pinned) {
        index = i
        break
      }
    }
    if (index < 0) break
    sorted.splice(index, 1)
  }
  return sorted
}

function persist(list: RecentRoute[]): RecentRoute[] {
  const next = trimToLimit(list)
  writeStoredList(RECENT_ROUTES_STORAGE_KEY, next)
  return next
}

export function saveRecentRoute(
  origin: Place,
  destination: Place,
  now: Date = new Date(),
): RecentRoute[] {
  const current = loadRecentRoutes()
  const storedOrigin = isCurrentLocation(origin) ? null : origin
  if (!isStoredPlace(destination) || (storedOrigin && !isStoredPlace(storedOrigin))) return current
  const id = recentRouteId(storedOrigin, destination)
  const searchedAt = now.toISOString()
  if (current.some((item) => item.id === id)) {
    return persist(current.map((item) => (item.id === id ? { ...item, searchedAt } : item)))
  }
  return persist([{ id, origin: storedOrigin, destination, searchedAt, pinned: false }, ...current])
}

export function removeRecentRoute(id: string): RecentRoute[] {
  return persist(loadRecentRoutes().filter((item) => item.id !== id))
}
