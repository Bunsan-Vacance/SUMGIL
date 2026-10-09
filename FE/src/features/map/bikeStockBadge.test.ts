import { describe, expect, it } from 'vitest'
import { bikeStockBadgeLabel, bikeStockBadgeLevel, bikeStockBadgeText } from './bikeStockBadge'

describe('따릉이 재고 배지', () => {
  it('재고 구간을 나눈다', () => {
    expect(bikeStockBadgeLevel(0)).toBe('low')
    expect(bikeStockBadgeLevel(2)).toBe('low')
    expect(bikeStockBadgeLevel(3)).toBe('ok')
    expect(bikeStockBadgeLevel(null)).toBe('unknown')
    expect(bikeStockBadgeLevel(undefined)).toBe('unknown')
  })

  it('표시 문구와 접근성 라벨을 만든다', () => {
    expect(bikeStockBadgeText(5)).toBe('5')
    expect(bikeStockBadgeText(0)).toBe('0')
    expect(bikeStockBadgeText(null)).toBe('?')
    expect(bikeStockBadgeLabel('강남역', 5)).toBe('강남역 · 대여 가능 5대')
    expect(bikeStockBadgeLabel('강남역', 0)).toBe('강남역 · 대여 가능 0대')
    expect(bikeStockBadgeLabel('강남역', undefined)).toBe('강남역 · 재고 알 수 없음')
  })
})
