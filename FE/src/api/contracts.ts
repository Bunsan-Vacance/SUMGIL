import type { Place, Route } from '../features/route/types'
import type { Mode, Priority } from '../features/route/types'

// Frontend ports, not a finalized backend HTTP/Swagger contract.
export interface RouteRequest {
  origin: Place
  destination: Place
  modes?: Mode[]
  priority?: Priority
  departedAt?: string
}
export interface RouteRepository {
  search(request: RouteRequest, signal: AbortSignal): Promise<Route[]>
}
export interface PlaceRepository {
  search(query: string, signal: AbortSignal): Promise<Place[]>
}

export interface StationSearchResult {
  stationId: string
  stationName: string
  lineId?: string
  lineName?: string
  lat?: number
  lng?: number
}

export interface StationRepository {
  search(query: string, signal: AbortSignal): Promise<StationSearchResult[]>
}

export interface NearbyBikeStation {
  id: string
  name: string
  address?: string
  lat: number
  lng: number
  dockCount?: number
  distanceMeters?: number
}

export interface BikeStationRequest {
  lat: number
  lng: number
  radiusMeters?: number
  limit?: number
}

export interface BikeStationRepository {
  nearby(request: BikeStationRequest, signal: AbortSignal): Promise<NearbyBikeStation[]>
  stock(rentalId: string, signal: AbortSignal): Promise<BikeStock>
}

export type BikeStockStatus = 'AVAILABLE' | 'STALE' | 'UNAVAILABLE'

export interface BikeStock {
  rentalId: string
  availableBikes: number | null
  stockUpdatedAt: string | null
  status: BikeStockStatus
  rackCount?: number | null
}
