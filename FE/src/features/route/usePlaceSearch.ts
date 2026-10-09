import { useEffect, useState } from 'react'
import { placeRepository, stationRepository } from '../../api/repositories'
import type { PlaceRepository, StationRepository, StationSearchResult } from '../../api/contracts'
import type { Place } from './types'

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

export function stationSearchResultToPlace(result: StationSearchResult): Place {
  const lineName = result.lineName?.trim()
  return {
    id: `station:${result.stationId}:${result.lineId || 'default'}`,
    name: `${result.stationName}${lineName ? ` (${lineName})` : ''}`,
    address: lineName || '지하철역',
    kind: '지하철역',
    stationId: result.stationId,
    ...(result.lat !== undefined && result.lng !== undefined
      ? { lat: result.lat, lng: result.lng }
      : {}),
  }
}

export function useStationSearch(
  query: string,
  repository: StationRepository | null = stationRepository,
) {
  const [stations, setStations] = useState<StationSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const request = new AbortController()
    const trimmed = query.trim()
    setError('')
    setStations([])
    if (!trimmed || !repository) {
      setLoading(false)
      return () => request.abort()
    }
    setLoading(true)
    const timer = window.setTimeout(() => {
      repository
        .search(trimmed, request.signal)
        .then((results) => {
          if (!request.signal.aborted) setStations(results)
        })
        .catch(() => {
          if (!request.signal.aborted)
            setError('역을 검색하지 못했어요. 검색어를 다시 입력해 주세요.')
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

  return { stations, loading, error }
}
