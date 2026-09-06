import { useEffect, useState } from 'react'
import { placeRepository } from '../../api/repositories'
import type { PlaceRepository } from '../../api/contracts'
import type { Place } from './types'

export function usePlaceSearch(query: string, repository: PlaceRepository = placeRepository) {
  const [places, setPlaces] = useState<Place[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    const request = new AbortController()
    setLoading(true)
    setError('')
    setPlaces([])
    repository
      .search(query, request.signal)
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
    return () => request.abort()
  }, [query, repository])
  return { places, loading, error }
}
