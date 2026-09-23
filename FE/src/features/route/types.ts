export type Mode = 'walk' | 'subway' | 'bus' | 'bike'
export type Priority = 'fast' | 'calm'
export type RouteSource = 'MOCK' | 'ALGORITHM'
export type TransitionType = 'BOARDING' | 'ALIGHTING' | 'TRANSFER' | 'BIKE_RENTAL' | 'BIKE_RETURN'

export type CongestionGrade = 'LOW' | 'MEDIUM' | 'HIGH'
export type SegmentCongestionGrade = 'RELAXED' | 'NORMAL' | 'CONGESTED' | 'SATURATED'
export type CongestionDataStatus = 'AVAILABLE' | 'LINE1_TRUNCATED' | 'NO_CALIBRATION' | 'NO_LOOKUP'
export type CongestionPredictionBasis = 'RECENT_7D' | 'PARTIAL' | 'WEEKDAY_AVERAGE' | 'LIVE'

export interface WorstSegmentCongestion {
  mode: 'SUBWAY' | 'BUS'
  fromNodeId: string | null
  toNodeId: string | null
  congestionPercent: number | null
}

export interface CongestionPrediction {
  congestionPercent: number | null
  congestionGrade: CongestionGrade | null
  dataStatus: CongestionDataStatus
  predictionBasis: CongestionPredictionBasis | null
  worstSegment?: WorstSegmentCongestion | null
}
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
  rentalId?: string
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
  rentalId?: string
}
export interface BusRouteOption {
  routeId: string
  routeName?: string
  headwayMin?: number
}
export interface Leg {
  distanceMeters?: number
  mode: Mode
  title: string
  note: string
  minutes: number
  transfer?: boolean
  transitionType?: TransitionType
  routeId?: string
  busRouteOptions?: BusRouteOption[]
  segmentCongestionLevel?: number
  segmentCongestionGrade?: SegmentCongestionGrade
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
  congestionPrediction?: CongestionPrediction
  source?: RouteSource
  modes: Mode[]
  line?: string
  legs: Leg[]
  geometry?: RouteGeometry
  departedAt?: string
}
