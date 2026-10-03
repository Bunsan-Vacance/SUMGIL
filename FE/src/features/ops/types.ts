// BE 계약 제안(TO_BE-ops-visualization-01) 기준, 확정 전. 필드명·의미는 BE 회신 뒤 바뀔 수 있다.

export type OpsDataSource = 'api' | 'mock'

/** 저장소가 돌려주는 결과 래퍼. 화면은 source로 "샘플" 배지를 정한다. */
export interface OpsResult<T> {
  source: OpsDataSource
  data: T
}

export type StockStatus = 'AVAILABLE' | 'STALE' | 'UNAVAILABLE'
export type PredictionStatus = 'AVAILABLE' | 'UNAVAILABLE'
export type PredictionSource = 'TABLE' | 'MODEL' | 'MOCK'

export interface BikeStockOverviewItem {
  rentalId: string
  name: string
  lat: number
  lng: number
  rackCount: number | null
  /** null은 "알 수 없음", 0은 "0대(부족)"로 구분한다. */
  availableBikes: number | null
  stockStatus: StockStatus
  stockUpdatedAt: string | null
  predictedBikes: number | null
  availabilityProbability: number | null
  predictionStatus: PredictionStatus
  predictionSource: PredictionSource | null
  predictedAt: string | null
}

export interface BikeStockOverview {
  arrivalTime: string | null
  count: number
  truncated: boolean
  generatedAt: string | null
  items: BikeStockOverviewItem[]
}

export interface HeatmapCell {
  timeSlot: number
  level: number | null
  nLinks: number | null
  nFallback: number | null
  maxLevel: number | null
}

export interface HeatmapLine {
  lineId: string
  lineName: string
  cells: HeatmapCell[]
}

export interface CongestionHeatmap {
  date: string
  source: string
  generatedAt: string | null
  predictorVersions: string[]
  slotFrom: number
  slotTo: number
  lines: HeatmapLine[]
}

export interface LatLng {
  lat: number
  lng: number
}

export interface BikeStockOverviewRequest {
  sw: LatLng
  ne: LatLng
  arrivalTime?: string
  limit?: number
}

export interface CongestionHeatmapRequest {
  /** YYYY-MM-DD. 생략하면 서버가 Asia/Seoul 오늘로 처리한다. */
  date?: string
}
