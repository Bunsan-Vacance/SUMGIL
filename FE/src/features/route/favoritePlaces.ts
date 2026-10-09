import { isRecord, isStoredPlace, readStoredList, writeStoredList } from './placeStorage'
import type { Place } from './types'

export type FavoriteLabel = 'home' | 'work'

export interface FavoritePlace {
  place: Place
  label: FavoriteLabel | null
  savedAt: string
}

export const FAVORITE_PLACES_STORAGE_KEY = 'sugil:favorite-places'
const FAVORITE_PLACES_LIMIT = 20

/** 현재 위치처럼 고정된 장소가 아닌 항목은 즐겨찾기로 등록할 수 없다. */
export function isRegisterablePlace(place: Place): boolean {
  return place.kind !== '현재 위치' && !place.id.startsWith('current-location:')
}

function labelRank(label: FavoriteLabel | null): number {
  if (label === 'home') return 0
  if (label === 'work') return 1
  return 2
}

/** 집 → 회사 → 나머지(저장 시각 최신순) 순서로 정렬한 새 배열을 돌려준다. */
export function sortFavoritePlaces(list: FavoritePlace[]): FavoritePlace[] {
  return [...list].sort((a, b) => {
    const rank = labelRank(a.label) - labelRank(b.label)
    if (rank !== 0) return rank
    return Date.parse(b.savedAt) - Date.parse(a.savedAt)
  })
}

function isFavoriteLabel(value: unknown): value is FavoriteLabel | null {
  return value === null || value === 'home' || value === 'work'
}

function normalizeFavoritePlaces(value: unknown): FavoritePlace[] {
  if (!Array.isArray(value)) return []
  const ids = new Set<string>()
  const usedLabels = new Set<FavoriteLabel>()
  const items: FavoritePlace[] = []
  for (const item of value) {
    if (!isRecord(item) || !isStoredPlace(item.place) || !isFavoriteLabel(item.label)) continue
    if (typeof item.savedAt !== 'string' || !Number.isFinite(Date.parse(item.savedAt))) continue
    if (ids.has(item.place.id)) continue
    ids.add(item.place.id)
    // 집·회사는 각각 하나만 유지하고 중복된 쪽은 일반 항목으로 내린다.
    let label = item.label
    if (label) {
      if (usedLabels.has(label)) label = null
      else usedLabels.add(label)
    }
    items.push({ place: item.place, label, savedAt: item.savedAt })
  }
  return sortFavoritePlaces(items)
}

export function loadFavoritePlaces(): FavoritePlace[] {
  return normalizeFavoritePlaces(readStoredList(FAVORITE_PLACES_STORAGE_KEY))
}

/** 한도를 넘으면 label 없는 가장 오래된 항목부터 제거한다. label 있는 항목은 제거하지 않는다. */
function trimToLimit(list: FavoritePlace[]): FavoritePlace[] {
  const sorted = sortFavoritePlaces(list)
  while (sorted.length > FAVORITE_PLACES_LIMIT) {
    let index = -1
    for (let i = sorted.length - 1; i >= 0; i -= 1) {
      if (sorted[i].label === null) {
        index = i
        break
      }
    }
    if (index < 0) break
    sorted.splice(index, 1)
  }
  return sorted
}

function persist(list: FavoritePlace[]): FavoritePlace[] {
  const next = trimToLimit(list)
  writeStoredList(FAVORITE_PLACES_STORAGE_KEY, next)
  return next
}

export function toggleFavoritePlace(place: Place): FavoritePlace[] {
  const current = loadFavoritePlaces()
  if (!isRegisterablePlace(place) || !isStoredPlace(place)) return current
  if (current.some((item) => item.place.id === place.id)) {
    return persist(current.filter((item) => item.place.id !== place.id))
  }
  return persist([...current, { place, label: null, savedAt: new Date().toISOString() }])
}

export function setFavoriteLabel(place: Place, label: FavoriteLabel): FavoritePlace[] {
  const current = loadFavoritePlaces()
  if (!isRegisterablePlace(place) || !isStoredPlace(place)) return current
  const lowered = current.map((item) =>
    item.label === label && item.place.id !== place.id ? { ...item, label: null } : item,
  )
  if (lowered.some((item) => item.place.id === place.id)) {
    return persist(lowered.map((item) => (item.place.id === place.id ? { ...item, label } : item)))
  }
  return persist([...lowered, { place, label, savedAt: new Date().toISOString() }])
}

export function removeFavoritePlace(id: string): FavoritePlace[] {
  return persist(loadFavoritePlaces().filter((item) => item.place.id !== id))
}
