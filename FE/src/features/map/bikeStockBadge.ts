export type BikeStockBadgeLevel = 'ok' | 'low' | 'unknown'

// 이 값 이하이면 재고 부족으로 표시한다.
export const BIKE_STOCK_LOW_MAX = 2

type StockCount = number | null | undefined

export function bikeStockBadgeLevel(count: StockCount): BikeStockBadgeLevel {
  if (count === null || count === undefined) return 'unknown'
  return count <= BIKE_STOCK_LOW_MAX ? 'low' : 'ok'
}

export function bikeStockBadgeText(count: StockCount): string {
  return count === null || count === undefined ? '?' : String(count)
}

export function bikeStockBadgeLabel(name: string, count: StockCount): string {
  return count === null || count === undefined
    ? `${name} · 재고 알 수 없음`
    : `${name} · 대여 가능 ${count}대`
}
