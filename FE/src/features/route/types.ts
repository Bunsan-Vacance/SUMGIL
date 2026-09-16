export type Mode = 'walk' | 'subway' | 'bus' | 'bike'
export type Priority = 'fast' | 'calm'
export interface Place {
  id: string
  name: string
  address: string
  kind: string
  stationId?: string
  lat?: number
  lng?: number
  placeUrl?: string
  dockCount?: number
  distanceMeters?: number
}
export type GeometryLineString = [number, number][]
export interface RouteGeometry {
  type: 'MultiLineString'
  coordinates: GeometryLineString[]
}
export interface RouteEndpoint {
  id?: string
  name?: string
  lat?: number
  lng?: number
}
export interface Leg {
  distanceMeters?: number
  mode: Mode
  title: string
  note: string
  minutes: number
  transfer?: boolean
  routeId?: string
  from?: RouteEndpoint
  to?: RouteEndpoint
  geometry?: RouteGeometry
}
export interface Route {
  routeType?: 'SHORTEST' | 'SHORTEST_WITH_BIKE' | 'ALTERNATIVE' | 'LOW_CONGESTION'
  totalDistanceMeters?: number
  id: string
  label: string
  minutes: number
  walk?: number
  transfers: number
  congestionPercent?: number
  modes: Mode[]
  line?: string
  legs: Leg[]
  geometry?: RouteGeometry
  departedAt?: string
}
