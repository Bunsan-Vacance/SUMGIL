// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest'
import type { KakaoMapInstance, KakaoMaps } from '../../lib/kakao/sdk'
import { createStationOverlay, stationMarkerLabel } from './stationMarkers'
import type { StationMarkerDatum } from './stationMarkers'

const datum: StationMarkerDatum = {
  stationId: '222',
  stationName: '강남',
  lat: 37.4979,
  lng: 127.0276,
  grade: 'NORMAL',
}

function fakeMaps(setMap = vi.fn()) {
  return {
    LatLng: class {
      constructor(
        readonly lat: number,
        readonly lng: number,
      ) {}
    },
    CustomOverlay: class {
      constructor(readonly options: Record<string, unknown>) {}
      setMap = setMap
    },
  } as unknown as KakaoMaps
}

describe('역 혼잡도 마커', () => {
  it('라벨 문구는 등급이 없으면 정보 없음이다', () => {
    expect(stationMarkerLabel('강남', 'CONGESTED')).toBe('강남 · 지금 혼잡')
    expect(stationMarkerLabel('강남', null)).toBe('강남 · 정보 없음')
  })

  it.each([
    ['RELAXED', 'grade-relaxed', '여유'],
    ['NORMAL', 'grade-normal', '보통'],
    ['CONGESTED', 'grade-congested', '혼잡'],
    ['SATURATED', 'grade-saturated', '포화'],
  ] as const)('%s 등급을 클래스와 문구로 보여 준다', (grade, className, label) => {
    const marker = createStationOverlay(
      fakeMaps(),
      {} as KakaoMapInstance,
      { ...datum, grade },
      false,
      vi.fn(),
    )
    expect(marker.element.classList.contains('station-marker')).toBe(true)
    expect(marker.element.classList.contains(className)).toBe(true)
    expect(marker.element.querySelector('.station-marker-grade')?.textContent).toBe(label)
    expect(marker.element.getAttribute('aria-label')).toBe(`강남 · 지금 ${label}`)
    expect(marker.element.textContent).toContain('강남')
  })

  it('등급이 null이면 grade-none과 정보 없음이다', () => {
    const marker = createStationOverlay(
      fakeMaps(),
      {} as KakaoMapInstance,
      { ...datum, grade: null },
      false,
      vi.fn(),
    )
    expect(marker.element.classList.contains('grade-none')).toBe(true)
    expect(marker.element.querySelector('.station-marker-grade')?.textContent).toBe('정보 없음')
    expect(marker.element.title).toBe('강남 · 정보 없음')
  })

  it('setGrade가 클래스·문구·라벨을 바꾸고 선택 상태는 유지한다', () => {
    const marker = createStationOverlay(fakeMaps(), {} as KakaoMapInstance, datum, true, vi.fn())
    marker.setGrade('SATURATED')
    expect(marker.element.classList.contains('grade-saturated')).toBe(true)
    expect(marker.element.classList.contains('grade-normal')).toBe(false)
    expect(marker.element.classList.contains('selected')).toBe(true)
    expect(marker.element.querySelector('.station-marker-grade')?.textContent).toBe('포화')
    marker.setGrade(null)
    expect(marker.element.classList.contains('grade-none')).toBe(true)
    expect(marker.element.getAttribute('aria-label')).toBe('강남 · 정보 없음')
  })

  it('setSelected가 selected 클래스와 aria-pressed를 바꾼다', () => {
    const marker = createStationOverlay(fakeMaps(), {} as KakaoMapInstance, datum, false, vi.fn())
    expect(marker.element.getAttribute('aria-pressed')).toBe('false')
    marker.setSelected(true)
    expect(marker.element.classList.contains('selected')).toBe(true)
    expect(marker.element.getAttribute('aria-pressed')).toBe('true')
  })

  it('클릭하면 onSelect를 호출하고 destroy 뒤에는 호출하지 않는다', () => {
    const setMap = vi.fn()
    const onSelect = vi.fn()
    const marker = createStationOverlay(
      fakeMaps(setMap),
      {} as KakaoMapInstance,
      datum,
      false,
      onSelect,
    )
    marker.element.click()
    expect(onSelect).toHaveBeenCalledOnce()
    marker.destroy()
    expect(setMap).toHaveBeenCalledWith(null)
    marker.element.click()
    expect(onSelect).toHaveBeenCalledOnce()
  })
})
