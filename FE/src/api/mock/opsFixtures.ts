import { bikeStations } from '../../features/map/bikeStations'
import type {
  BikeStockOverview,
  BikeStockOverviewItem,
  BikeStockOverviewRequest,
  CongestionHeatmap,
  HeatmapLine,
  PredictionStatus,
  StockStatus,
} from '../../features/ops/types'

// 운영자 뷰 샘플 데이터. 실제 값이 아니며 화면에 "샘플" 배지로 표시된다. 같은 입력이면 항상 같은 결과다.

const SAMPLE_LIMIT = 30
const BASE_TIME = '2026-10-03T09:00:00+09:00'
const stockPattern: readonly StockStatus[] = [
  'AVAILABLE',
  'AVAILABLE',
  'AVAILABLE',
  'STALE',
  'AVAILABLE',
  'UNAVAILABLE',
]
const predictionPattern: readonly PredictionStatus[] = [
  'AVAILABLE',
  'AVAILABLE',
  'UNAVAILABLE',
  'AVAILABLE',
]

export function buildBikeStockSample(request: BikeStockOverviewRequest): BikeStockOverview {
  const { sw, ne } = request
  const inside = bikeStations.filter(
    (station) =>
      station.lat >= sw.lat &&
      station.lat <= ne.lat &&
      station.lng >= sw.lng &&
      station.lng <= ne.lng,
  )
  const items: BikeStockOverviewItem[] = inside.slice(0, SAMPLE_LIMIT).map((station, index) => {
    const stockStatus = stockPattern[index % stockPattern.length]
    const predictionStatus = predictionPattern[index % predictionPattern.length]
    const rackCount = 10 + ((index * 3) % 15)
    // 0대와 null을 모두 포함한다: 3의 배수 순번은 0대, UNAVAILABLE은 null.
    const availableBikes =
      stockStatus === 'UNAVAILABLE' ? null : index % 3 === 0 ? 0 : (index * 7) % (rackCount + 1)
    const predictedBikes =
      predictionStatus === 'UNAVAILABLE' ? null : (index * 5 + 1) % (rackCount + 1)
    return {
      rentalId: station.id,
      name: station.name,
      lat: station.lat,
      lng: station.lng,
      rackCount: stockStatus === 'UNAVAILABLE' ? null : rackCount,
      availableBikes,
      stockStatus,
      stockUpdatedAt: stockStatus === 'UNAVAILABLE' ? null : BASE_TIME,
      predictedBikes,
      availabilityProbability:
        predictedBikes === null ? null : Math.min(1, Math.round((predictedBikes / 8) * 100) / 100),
      predictionStatus,
      predictionSource: predictionStatus === 'UNAVAILABLE' ? null : 'MOCK',
      predictedAt: predictionStatus === 'UNAVAILABLE' ? null : BASE_TIME,
    }
  })
  return {
    arrivalTime: request.arrivalTime ?? null,
    count: items.length,
    truncated: inside.length > SAMPLE_LIMIT,
    generatedAt: BASE_TIME,
    items,
  }
}

const SLOT_FROM = 10
const SLOT_TO = 47
const lineSamples = Array.from({ length: 8 }, (_, i) => ({
  lineId: String(i + 1),
  lineName: `${i + 1}호선`,
}))

function buildLine(line: { lineId: string; lineName: string }, lineIndex: number): HeatmapLine {
  const cells = []
  for (let slot = SLOT_FROM; slot <= SLOT_TO; slot += 1) {
    // 출근(07:30~09:00)·퇴근(18:00~19:30) 피크가 있는 완만한 곡선에 호선별 오프셋을 더한다.
    const morning = Math.max(0, 60 - Math.abs(slot - 17) * 12)
    const evening = Math.max(0, 70 - Math.abs(slot - 37) * 12)
    const level = Math.round(35 + lineIndex * 6 + morning + evening)
    const missing = (lineIndex + slot) % 17 === 0 || (lineIndex === 7 && slot < 14)
    cells.push(
      missing
        ? { timeSlot: slot, level: null, nLinks: null, nFallback: null, maxLevel: null }
        : {
            timeSlot: slot,
            level,
            nLinks: 20 + lineIndex * 4,
            nFallback: (lineIndex + slot) % 5,
            maxLevel: level + 25,
          },
    )
  }
  return { ...line, cells }
}

export function buildHeatmapSample(date?: string): CongestionHeatmap {
  return {
    date: date ?? '2026-10-03',
    source: 'congestion_pred',
    generatedAt: BASE_TIME,
    predictorVersions: ['mock-sample'],
    slotFrom: SLOT_FROM,
    slotTo: SLOT_TO,
    lines: lineSamples.map(buildLine),
  }
}
