import { describe, expect, it } from 'vitest'
import { heatmapCellTone, stockLevel } from './useOpsData'

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

describe('heatmapCellTone', () => {
  it('null은 none이다', () => {
    expect(heatmapCellTone(null)).toBe('none')
    expect(heatmapCellTone(Number.NaN)).toBe('none')
  })
  it('잠정 임계 60/90/120/150으로 5구간을 나눈다', () => {
    expect(heatmapCellTone(0)).toBe('tone-1')
    expect(heatmapCellTone(59.9)).toBe('tone-1')
    expect(heatmapCellTone(60)).toBe('tone-2')
    expect(heatmapCellTone(89)).toBe('tone-2')
    expect(heatmapCellTone(90)).toBe('tone-3')
    expect(heatmapCellTone(120)).toBe('tone-4')
    expect(heatmapCellTone(150)).toBe('tone-5')
    expect(heatmapCellTone(300)).toBe('tone-5')
  })
})
