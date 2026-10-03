// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest'
import type { KakaoMapInstance, KakaoMaps } from '../../lib/kakao/sdk'
import { stockLabel, syncStockOverlays } from './bikeStockLayer'
import type { BikeStockOverviewItem } from './types'

function fakeMaps() {
  const created: { map: unknown; setMap: ReturnType<typeof vi.fn> }[] = []
  class LatLng {
    constructor(
      private lat: number,
      private lng: number,
    ) {}
    getLat() {
      return this.lat
    }
    getLng() {
      return this.lng
    }
  }
  class CustomOverlay {
    setMap = vi.fn()
    constructor(options: { map: unknown }) {
      created.push({ map: options.map, setMap: this.setMap })
    }
  }
  return { maps: { LatLng, CustomOverlay } as unknown as KakaoMaps, created }
}

const map = {} as KakaoMapInstance

function item(rentalId: string, overrides: Partial<BikeStockOverviewItem> = {}) {
  return {
    rentalId,
    name: `대여소 ${rentalId}`,
    lat: 37.5,
    lng: 127,
    rackCount: 10,
    availableBikes: 3,
    stockStatus: 'AVAILABLE',
    stockUpdatedAt: null,
    predictedBikes: 4,
    availabilityProbability: null,
    predictionStatus: 'AVAILABLE',
    predictionSource: 'MOCK',
    predictedAt: null,
    ...overrides,
  } as BikeStockOverviewItem
}

describe('재고 레이어 동기화', () => {
  it('항목마다 오버레이를 만들고 재고 수준 클래스를 붙인다', () => {
    const { maps, created } = fakeMaps()
    const result = syncStockOverlays(
      maps,
      map,
      [
        item('a', { availableBikes: 0 }),
        item('b', { availableBikes: 3 }),
        item('c', { availableBikes: 9 }),
        item('d', { availableBikes: null, predictedBikes: null }),
      ],
      new Map(),
    )
    expect(created).toHaveLength(4)
    expect(result.get('a')?.overlay.element.classList.contains('ops-stock-low')).toBe(true)
    expect(result.get('b')?.overlay.element.classList.contains('ops-stock-mid')).toBe(true)
    expect(result.get('c')?.overlay.element.classList.contains('ops-stock-good')).toBe(true)
    expect(result.get('d')?.overlay.element.classList.contains('ops-stock-unknown')).toBe(true)
  })

  it('null과 0을 구분해 title·aria-label에 쓴다', () => {
    expect(stockLabel(item('a'))).toBe('대여소 a · 재고 3대 · +예측 4대')
    expect(stockLabel(item('a', { availableBikes: 0 }))).toContain('재고 0대')
    expect(stockLabel(item('a', { availableBikes: null, predictedBikes: null }))).toBe(
      '대여소 a · 재고 알 수 없음 · +예측 알 수 없음',
    )
    const { maps } = fakeMaps()
    const result = syncStockOverlays(maps, map, [item('a', { availableBikes: 0 })], new Map())
    const element = result.get('a')!.overlay.element
    expect(element.title).toBe(element.getAttribute('aria-label'))
    expect(element.title).toContain('재고 0대')
  })

  it('기존 항목은 재사용·클래스 갱신하고 사라진 항목은 제거한다', () => {
    const { maps, created } = fakeMaps()
    const first = syncStockOverlays(maps, map, [item('a'), item('b')], new Map())
    expect(created).toHaveLength(2)
    const second = syncStockOverlays(
      maps,
      map,
      [item('a', { availableBikes: 1 }), item('c')],
      first,
    )
    expect(created).toHaveLength(3) // c만 새로 생성
    expect(second.get('a')).toBe(first.get('a'))
    expect(second.get('a')?.overlay.element.classList.contains('ops-stock-low')).toBe(true)
    expect(second.get('a')?.overlay.element.classList.contains('ops-stock-mid')).toBe(false)
    expect(second.has('b')).toBe(false)
    expect(created[1].setMap).toHaveBeenCalledWith(null) // b 제거
    expect(created[0].setMap).not.toHaveBeenCalled()
  })

  it('좌표가 바뀐 항목은 이전 오버레이를 없애고 다시 만든다', () => {
    const { maps, created } = fakeMaps()
    const first = syncStockOverlays(maps, map, [item('a')], new Map())
    const second = syncStockOverlays(maps, map, [item('a', { lat: 37.6 })], first)
    expect(created).toHaveLength(2)
    expect(created[0].setMap).toHaveBeenCalledWith(null)
    expect(second.get('a')).not.toBe(first.get('a'))
  })
})
