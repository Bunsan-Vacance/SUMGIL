// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest'
import type { KakaoMapInstance, KakaoMaps, MapPoint } from '../../lib/kakao/sdk'
import {
  createBikeStationClusterOverlay,
  createBikeStationOverlay,
  groupVisibleBikeStations,
  visibleBikeStations,
  zoomToBikeStationCluster,
} from './bikeStationMarkers'

const station = {
  id: 'ST-1',
  name: '강남역',
  address: '서울 강남구 테헤란로',
  lat: 37.5,
  lng: 127,
}

describe('따릉이 지도 마커', () => {
  it('접근 가능한 버튼 CustomOverlay를 만들고 선택 상태를 토글한다', () => {
    const setMap = vi.fn()
    const maps = {
      LatLng: class {
        constructor(
          readonly lat: number,
          readonly lng: number,
        ) {}
        getLat() {
          return this.lat
        }
        getLng() {
          return this.lng
        }
      },
      CustomOverlay: class {
        constructor(readonly options: Record<string, unknown>) {}
        setMap = setMap
      },
    } as unknown as KakaoMaps
    const map = {} as KakaoMapInstance

    const marker = createBikeStationOverlay(maps, map, station, false, vi.fn())
    expect(marker.element.tagName).toBe('BUTTON')
    expect(marker.element.getAttribute('aria-label')).toContain('강남역')
    expect(marker.element.classList.contains('selected')).toBe(false)
    marker.setSelected(true)
    expect(marker.element.classList.contains('selected')).toBe(true)
    marker.setRouteActive(true)
    expect(marker.element.classList.contains('route-active')).toBe(true)
    marker.setRouteActive(false)
    expect(marker.element.classList.contains('route-active')).toBe(false)
    marker.destroy()
    expect(setMap).toHaveBeenCalledWith(null)

    const fallbackMarker = createBikeStationOverlay(
      maps,
      map,
      { ...station, name: '따릉이 대여소 ST-1' },
      false,
      vi.fn(),
    )
    expect(fallbackMarker.element.getAttribute('aria-label')).toContain(station.address)
    expect(fallbackMarker.element.getAttribute('aria-label')).not.toContain('ST-1')
    fallbackMarker.destroy()
  })

  it('현재 지도 bounds 안의 대여소만 선택한다', () => {
    const maps = {
      LatLng: class {
        constructor(
          readonly lat: number,
          readonly lng: number,
        ) {}
        getLat() {
          return this.lat
        }
        getLng() {
          return this.lng
        }
      },
    } as unknown as KakaoMaps
    const map = {
      getBounds: () => ({
        contain: (value: MapPoint) => value.getLat() === 37.5 && value.getLng() === 127,
      }),
    } as KakaoMapInstance

    expect(visibleBikeStations(maps, map, [station])).toEqual([station])
    expect(visibleBikeStations(maps, map, [{ ...station, lat: 37.51 }])).toEqual([])
  })

  it('축소 단계에서는 화면 격자로 묶되 대여소 수를 보존한다', () => {
    const maps = {
      LatLng: class {
        constructor(
          readonly lat: number,
          readonly lng: number,
        ) {}
        getLat() {
          return this.lat
        }
        getLng() {
          return this.lng
        }
      },
    } as unknown as KakaoMaps
    const stations = [
      station,
      { ...station, id: 'ST-2', lat: 37.5001, lng: 127.0001 },
      { ...station, id: 'ST-3', lat: 37.51, lng: 127.01 },
    ]
    const map = {
      getBounds: () => ({ contain: () => true }),
      getLevel: () => 6,
      getProjection: () => ({
        containerPointFromCoords: (point: MapPoint) =>
          point.getLat() === 37.51 ? { x: 100, y: 100 } : { x: 10, y: 10 },
      }),
    } as unknown as KakaoMapInstance

    const groups = groupVisibleBikeStations(maps, map, stations)
    expect(groups.map((group) => group.stations.length).sort()).toEqual([1, 2])
    expect(groups.flatMap((group) => group.stations)).toHaveLength(stations.length)

    const closeMap = { ...map, getLevel: () => 5 } as unknown as KakaoMapInstance
    expect(groupVisibleBikeStations(maps, closeMap, stations)).toHaveLength(3)
    expect(
      groupVisibleBikeStations(maps, closeMap, stations).every(
        (group) => group.stations.length === 1,
      ),
    ).toBe(true)
  })

  it('클러스터 버튼은 확대하고 제거 시 overlay를 정리한다', () => {
    const setMap = vi.fn()
    const maps = {
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
    const map = {
      getLevel: vi.fn(() => 8),
      setLevel: vi.fn(),
    } as unknown as KakaoMapInstance
    const group = {
      stations: [station, { ...station, id: 'ST-2' }],
      center: { lat: 37.5, lng: 127 },
    }
    const onZoom = vi.fn(() => zoomToBikeStationCluster(maps, map, group))
    const cluster = createBikeStationClusterOverlay(maps, map, group, onZoom, true)

    expect(cluster.element.classList.contains('route-active')).toBe(true)
    expect(cluster.element.getAttribute('aria-label')).toBe(
      '이 지역 따릉이 대여소 2개, 확대해서 보기',
    )
    cluster.element.click()
    expect(onZoom).toHaveBeenCalledOnce()
    expect(map.setLevel).toHaveBeenCalledWith(6, { anchor: expect.anything() })
    cluster.destroy()
    expect(setMap).toHaveBeenCalledWith(null)
  })
})
