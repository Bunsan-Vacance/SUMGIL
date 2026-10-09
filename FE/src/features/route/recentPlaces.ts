import { isStoredPlace, readStoredList, writeStoredList } from './placeStorage'
import type { Place } from './types'

export const RECENT_PLACES_STORAGE_KEY = 'sugil:recent-places'
const RECENT_PLACES_LIMIT = 10

function normalizeRecentPlaces(value: unknown): Place[] {
  if (!Array.isArray(value)) return []
  const ids = new Set<string>()
  return value
    .filter((place): place is Place => {
      if (!isStoredPlace(place) || ids.has(place.id)) return false
      ids.add(place.id)
      return true
    })
    .slice(0, RECENT_PLACES_LIMIT)
}

export function loadRecentPlaces(): Place[] {
  return normalizeRecentPlaces(readStoredList(RECENT_PLACES_STORAGE_KEY))
}

export function saveRecentPlace(place: Place): Place[] {
  const current = loadRecentPlaces()
  if (!isStoredPlace(place)) return current
  const places = [place, ...current.filter((item) => item.id !== place.id)].slice(
    0,
    RECENT_PLACES_LIMIT,
  )
  writeStoredList(RECENT_PLACES_STORAGE_KEY, places)
  return places
}

export function removeRecentPlace(id: string): Place[] {
  const places = loadRecentPlaces().filter((place) => place.id !== id)
  writeStoredList(RECENT_PLACES_STORAGE_KEY, places)
  return places
}

export function clearRecentPlaces(): Place[] {
  writeStoredList(RECENT_PLACES_STORAGE_KEY, [])
  return []
}
