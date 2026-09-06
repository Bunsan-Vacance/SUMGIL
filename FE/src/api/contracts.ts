import type { Place, Route } from '../features/route/types'

// Frontend ports, not a finalized backend HTTP/Swagger contract.
export interface RouteRequest {
  origin: Place
  destination: Place
}
export interface RouteRepository {
  search(request: RouteRequest, signal: AbortSignal): Promise<Route[]>
}
export interface PlaceRepository {
  search(query: string, signal: AbortSignal): Promise<Place[]>
}
