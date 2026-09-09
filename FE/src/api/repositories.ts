import { mockRouteRepository } from './mock/repositories'
import {
  loadKakaoMaps,
  type KakaoMaps,
  type KakaoPlaceSearchResult,
  type KakaoAddressSearchResult,
} from '../lib/kakao/sdk'
import type { PlaceRepository } from './contracts'
import type { Place } from '../features/route/types'
import { searchBikeStations } from '../features/map/bikeStations'

const abortError = () => new DOMException('Aborted', 'AbortError')

function validCoordinate(value: string | number, min: number, max: number) {
  if (typeof value === 'string' && !value.trim()) return null
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) && number >= min && number <= max ? number : null
}

function validUrl(value?: string) {
  const trimmed = value?.trim()
  if (!trimmed) return undefined
  try {
    const url = new URL(trimmed)
    return url.protocol === 'http:' || url.protocol === 'https:' ? trimmed : undefined
  } catch {
    return undefined
  }
}

function placeFromKeyword(result: KakaoPlaceSearchResult): Place | null {
  const lat = validCoordinate(result.y, -90, 90)
  const lng = validCoordinate(result.x, -180, 180)
  const name = result.place_name?.trim()
  const address = (result.road_address_name || result.address_name || '').trim()
  if (lat === null || lng === null || !name || !address) return null
  return {
    id: result.id?.trim() || `place-${lat}-${lng}`,
    name,
    address,
    kind: result.category_group_name?.trim() || result.category_name?.split(' > ').at(-1) || '장소',
    lat,
    lng,
    placeUrl: validUrl(result.place_url),
  }
}

function placeFromAddress(result: KakaoAddressSearchResult): Place | null {
  const lat = validCoordinate(result.y, -90, 90)
  const lng = validCoordinate(result.x, -180, 180)
  const address = result.address_name?.trim()
  if (lat === null || lng === null || !address) return null
  return {
    id: `address-${lat}-${lng}`,
    name: address,
    address,
    kind: '주소',
    lat,
    lng,
  }
}

type MapsLoader = () => Promise<KakaoMaps>

export function createKakaoPlaceRepository(loadMaps: MapsLoader = loadKakaoMaps): PlaceRepository {
  return {
    search(query, signal) {
      const trimmed = query.trim()
      if (!trimmed) return Promise.resolve([])
      return new Promise<Place[]>((resolve, reject) => {
        let settled = false
        const settle = (fn: () => void) => {
          if (settled || signal.aborted) return
          settled = true
          signal.removeEventListener('abort', onAbort)
          fn()
        }
        const onAbort = () => {
          if (settled) return
          settled = true
          reject(abortError())
        }
        signal.addEventListener('abort', onAbort, { once: true })
        if (signal.aborted) {
          onAbort()
          return
        }
        loadMaps()
          .then((maps) => {
            if (signal.aborted || settled) return
            const places = new maps.services.Places()
            const geocoder = new maps.services.Geocoder()
            const searchAddress = () => {
              geocoder.addressSearch(trimmed, (results, status) => {
                if (signal.aborted || settled) return
                if (status === maps.services.Status.ZERO_RESULT) {
                  settle(() => resolve([]))
                  return
                }
                if (status !== maps.services.Status.OK) {
                  settle(() => reject(new Error('place-search-failed')))
                  return
                }
                settle(() =>
                  resolve(results.map(placeFromAddress).filter((place): place is Place => !!place)),
                )
              })
            }
            places.keywordSearch(trimmed, (results, status) => {
              if (signal.aborted || settled) return
              if (status === maps.services.Status.ZERO_RESULT) {
                searchAddress()
                return
              }
              if (status !== maps.services.Status.OK) {
                settle(() => reject(new Error('place-search-failed')))
                return
              }
              const mapped = results
                .map(placeFromKeyword)
                .filter((place): place is Place => !!place)
              if (mapped.length) settle(() => resolve(mapped))
              else searchAddress()
            })
          })
          .catch((error: unknown) => {
            if (signal.aborted || settled) return
            settle(() => reject(error))
          })
      })
    },
  }
}

// Replace these adapters when the backend contract is agreed. UI imports only ports.
export const routeRepository = mockRouteRepository
export const placeRepository = createKakaoPlaceRepository()
export const bikeStationRepository: PlaceRepository = {
  search(query, signal) {
    if (signal.aborted) return Promise.reject(abortError())
    return Promise.resolve(searchBikeStations(query))
  },
}
