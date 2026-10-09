// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { NearbyStation } from '../../api/contracts'
import type { Place } from '../route/types'
import { availableLayers } from './homeLayers'
import { useHomeMapLayers } from './useHomeMapLayers'

const bike: Place = {
  id: 'bike-station:ST-1',
  name: '강남역 1번출구',
  address: '서울',
  kind: '따릉이 대여소',
  lat: 37.5,
  lng: 127,
}
const subway: NearbyStation = {
  stationId: '222',
  stationName: '강남',
  lat: 37.4979,
  lng: 127.0276,
  distanceMeters: 100,
  lines: [],
}

describe('홈 지도 레이어 상태', () => {
  it('기본 레이어는 availableLayers의 첫 번째 값이다', () => {
    const { result } = renderHook(() => useHomeMapLayers())
    expect(result.current.layer).toBe(availableLayers[0] ?? null)
    expect(result.current.selection).toBeNull()
  })

  it('대여소와 역 선택은 서로를 덮어쓴다', () => {
    const { result } = renderHook(() => useHomeMapLayers(true, 'bike'))
    act(() => result.current.selectBikeStation(bike))
    expect(result.current.selection).toEqual({ kind: 'bike', place: bike })
    act(() => result.current.selectSubwayStation(subway))
    expect(result.current.selection).toEqual({ kind: 'subway', station: subway })
    act(() => result.current.selectBikeStation(bike))
    expect(result.current.selection?.kind).toBe('bike')
  })

  it('대여소가 아닌 장소는 무시하고 clearSelection으로 해제한다', () => {
    const { result } = renderHook(() => useHomeMapLayers(true, 'bike'))
    act(() => result.current.selectBikeStation({ ...bike, kind: '지하철역' }))
    expect(result.current.selection).toBeNull()
    act(() => result.current.selectBikeStation(bike))
    act(() => result.current.clearSelection())
    expect(result.current.selection).toBeNull()
  })

  it('레이어를 바꾸면 꺼진 레이어의 선택만 해제한다', () => {
    const { result } = renderHook(() => useHomeMapLayers(true, 'bike'))
    act(() => result.current.selectBikeStation(bike))
    act(() => result.current.setLayer('crowd'))
    expect(result.current.selection).toBeNull()
    act(() => result.current.selectSubwayStation(subway))
    act(() => result.current.setLayer('bike'))
    expect(result.current.selection).toBeNull()
    act(() => result.current.selectSubwayStation(subway))
    act(() => result.current.setLayer('crowd'))
    expect(result.current.selection?.kind).toBe('subway')
    act(() => result.current.setLayer(null))
    expect(result.current.selection).toBeNull()
  })

  it('홈을 벗어나면 선택을 해제하고 비활성 동안은 선택하지 않는다', () => {
    const { result, rerender } = renderHook(({ active }) => useHomeMapLayers(active, 'bike'), {
      initialProps: { active: true },
    })
    act(() => result.current.selectBikeStation(bike))
    rerender({ active: false })
    expect(result.current.selection).toBeNull()
    act(() => result.current.selectSubwayStation(subway))
    act(() => result.current.selectBikeStation(bike))
    expect(result.current.selection).toBeNull()
  })
})
