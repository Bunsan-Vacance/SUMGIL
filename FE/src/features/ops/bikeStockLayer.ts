import type { KakaoMapInstance, KakaoMaps } from '../../lib/kakao/sdk'
import { createBikeStationOverlay, type BikeStationOverlay } from '../map/bikeStationMarkers'
import type { BikeStockOverviewItem } from './types'
import { stockLevel, type StockLevel } from './useOpsData'

export interface StockOverlay {
  overlay: BikeStationOverlay
  lat: number
  lng: number
}

const LEVEL_CLASSES: Record<StockLevel, string> = {
  low: 'ops-stock-low',
  mid: 'ops-stock-mid',
  good: 'ops-stock-good',
  unknown: 'ops-stock-unknown',
}
const ALL_LEVEL_CLASSES = Object.values(LEVEL_CLASSES)

/** null은 "알 수 없음", 0은 "0대"로 구분해 표기한다. */
function countText(value: number | null) {
  return value === null ? '알 수 없음' : `${value}대`
}

export function stockLabel(item: BikeStockOverviewItem) {
  return `${item.name} · 재고 ${countText(item.availableBikes)} · +예측 ${countText(item.predictedBikes)}`
}

function applyStock(overlay: BikeStationOverlay, item: BikeStockOverviewItem) {
  const { element } = overlay
  element.classList.remove(...ALL_LEVEL_CLASSES)
  element.classList.add(LEVEL_CLASSES[stockLevel(item.availableBikes, item.predictedBikes)])
  const label = stockLabel(item)
  element.title = label
  element.setAttribute('aria-label', label)
}

const noop = () => {}

/**
 * rentalId 기준으로 오버레이를 만들고·갱신하고·제거한다. 좌표가 바뀐 항목은 다시 만든다.
 * 입력 맵은 수정하지 않고 갱신된 새 맵을 돌려준다.
 */
export function syncStockOverlays(
  maps: KakaoMaps,
  map: KakaoMapInstance,
  items: BikeStockOverviewItem[],
  existing: Map<string, StockOverlay>,
): Map<string, StockOverlay> {
  const next = new Map<string, StockOverlay>()
  for (const item of items) {
    const prev = existing.get(item.rentalId)
    if (prev && prev.lat === item.lat && prev.lng === item.lng) {
      applyStock(prev.overlay, item)
      next.set(item.rentalId, prev)
      continue
    }
    prev?.overlay.destroy()
    const overlay = createBikeStationOverlay(
      maps,
      map,
      { id: item.rentalId, name: item.name, address: '', lat: item.lat, lng: item.lng },
      false,
      noop,
    )
    applyStock(overlay, item)
    next.set(item.rentalId, { overlay, lat: item.lat, lng: item.lng })
  }
  for (const [id, stale] of existing) {
    if (!next.has(id)) stale.overlay.destroy()
  }
  return next
}

export function destroyStockOverlays(overlays: Map<string, StockOverlay>) {
  for (const { overlay } of overlays.values()) overlay.destroy()
}
