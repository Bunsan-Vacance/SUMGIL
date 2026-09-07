import { useEffect, useState } from 'react'
import { placeRepository } from '../../api/repositories'
import type { PlaceRepository } from '../../api/contracts'
import type { Place } from './types'

export const RECENT_PLACES_STORAGE_KEY = 'sugil:recent-places'
const RECENT_PLACES_LIMIT = 10

function getStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isValidCoordinate(value: unknown, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}

function isStoredPlace(value: unknown): value is Place {
  if (!isRecord(value)) return false
  if (
    typeof value.id !== 'string' ||
    !value.id.trim() ||
    typeof value.name !== 'string' ||
    !value.name.trim() ||
    typeof value.address !== 'string' ||
    !value.address.trim() ||
    typeof value.kind !== 'string' ||
    !value.kind.trim()
  )
    return false
  if ((value.lat === undefined) !== (value.lng === undefined)) return false
  if (value.lat !== undefined && !isValidCoordinate(value.lat, -90, 90)) return false
  if (value.lng !== undefined && !isValidCoordinate(value.lng, -180, 180)) return false
  if (value.placeUrl !== undefined) {
    if (typeof value.placeUrl !== 'string' || !value.placeUrl.trim()) return false
    try {
      const protocol = new URL(value.placeUrl).protocol
      if (protocol !== 'http:' && protocol !== 'https:') return false
    } catch {
      return false
    }
  }
  return true
}

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
  const storage = getStorage()
  if (!storage) return []
  try {
    const raw = storage.getItem(RECENT_PLACES_STORAGE_KEY)
    return normalizeRecentPlaces(raw ? JSON.parse(raw) : [])
  } catch {
    return []
  }
}

function writeRecentPlaces(places: Place[]) {
  try {
    getStorage()?.setItem(RECENT_PLACES_STORAGE_KEY, JSON.stringify(places))
  } catch {
    // 저장소를 사용할 수 없어도 검색 화면은 계속 동작한다.
  }
}

export function saveRecentPlace(place: Place): Place[] {
  const current = loadRecentPlaces()
  if (!isStoredPlace(place)) return current
  const places = [place, ...current.filter((item) => item.id !== place.id)].slice(
    0,
    RECENT_PLACES_LIMIT,
  )
  writeRecentPlaces(places)
  return places
}

export function removeRecentPlace(id: string): Place[] {
  const places = loadRecentPlaces().filter((place) => place.id !== id)
  writeRecentPlaces(places)
  return places
}

export function clearRecentPlaces(): Place[] {
  writeRecentPlaces([])
  return []
}

export function usePlaceSearch(query: string, repository: PlaceRepository = placeRepository) {
  const [places, setPlaces] = useState<Place[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const request = new AbortController()
    const trimmed = query.trim()
    setError('')
    setPlaces([])
    if (!trimmed) {
      setLoading(false)
      return () => request.abort()
    }
    setLoading(true)
    const timer = window.setTimeout(() => {
      repository
        .search(trimmed, request.signal)
        .then((results) => {
          if (!request.signal.aborted) setPlaces(results)
        })
        .catch(() => {
          if (!request.signal.aborted)
            setError('장소를 검색하지 못했어요. 검색어를 다시 입력해 주세요.')
        })
        .finally(() => {
          if (!request.signal.aborted) setLoading(false)
        })
    }, 300)
    return () => {
      window.clearTimeout(timer)
      request.abort()
    }
  }, [query, repository])
  return { places, loading, error }
}
