import type { Place, Route } from '../features/route/types'
import type { Mode, Priority } from '../features/route/types'
import type {
  BikeStockOverview,
  BikeStockOverviewRequest,
  CongestionHeatmap,
  CongestionHeatmapRequest,
  OpsResult,
} from '../features/ops/types'

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
  availableBikes?: number | null
  stockUpdatedAt?: string | null
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

// 운영자 뷰 읽기 API. BE 계약 제안(TO_BE-ops-visualization-01) 기준, 확정 전.
export interface OpsRepository {
  bikeStockOverview(
    request: BikeStockOverviewRequest,
    signal: AbortSignal,
  ): Promise<OpsResult<BikeStockOverview>>
  congestionHeatmap(
    request: CongestionHeatmapRequest,
    signal: AbortSignal,
  ): Promise<OpsResult<CongestionHeatmap>>
}
