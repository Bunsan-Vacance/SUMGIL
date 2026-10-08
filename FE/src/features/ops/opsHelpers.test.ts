import { describe, expect, it } from 'vitest'
import { STOCK_GOOD_MIN, STOCK_LOW_MAX, heatmapCellTone, stockLevel } from './useOpsData'

describe('stockLevel', () => {
  it('재고 기준으로 부족·보통·여유를 나눈다', () => {
    expect(stockLevel(0, null)).toBe('low')
    expect(stockLevel(2, 9)).toBe('low')
    expect(stockLevel(3, null)).toBe('mid')
    expect(stockLevel(4, null)).toBe('mid')
    expect(stockLevel(5, 0)).toBe('good')
  })
  it('재고가 null이면 예측값을 쓰고 둘 다 null이면 알 수 없음이다', () => {
    expect(stockLevel(null, 1)).toBe('low')
    expect(stockLevel(null, 7)).toBe('good')
    expect(stockLevel(null, null)).toBe('unknown')
  })
  it('0은 null과 달리 부족이다', () => {
    expect(stockLevel(0, null)).not.toBe('unknown')
  })
})

describe('재고 임계 상수', () => {
  it('경계값에서 구간이 갈린다', () => {
    expect(STOCK_LOW_MAX).toBe(2)
    expect(STOCK_GOOD_MIN).toBe(5)
    expect(stockLevel(STOCK_LOW_MAX, null)).toBe('low')
    expect(stockLevel(STOCK_LOW_MAX + 1, null)).toBe('mid')
    expect(stockLevel(STOCK_GOOD_MIN - 1, null)).toBe('mid')
    expect(stockLevel(STOCK_GOOD_MIN, null)).toBe('good')
  })
})

describe('heatmapCellTone', () => {
  it('null·NaN은 데이터 없음이다', () => {
    expect(heatmapCellTone(null)).toBe('none')
    expect(heatmapCellTone(Number.NaN)).toBe('none')
  })
  it('사용자 지도와 같은 40/70/100 등급 경계를 쓴다', () => {
    expect(heatmapCellTone(0)).toBe('RELAXED')
    expect(heatmapCellTone(39.9)).toBe('RELAXED')
    expect(heatmapCellTone(40)).toBe('NORMAL')
    expect(heatmapCellTone(69.9)).toBe('NORMAL')
    expect(heatmapCellTone(70)).toBe('CONGESTED')
    expect(heatmapCellTone(99.9)).toBe('CONGESTED')
    expect(heatmapCellTone(100)).toBe('SATURATED')
    expect(heatmapCellTone(300)).toBe('SATURATED')
  })
})
