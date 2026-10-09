// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Place } from '../route/types'
import { useHomeMapLayers } from './useHomeMapLayers'

const station: Place = {
  id: 'bike-station:ST-1',
  name: '강남역',
  address: '서울',
  kind: '따릉이 대여소',
  lat: 37.5,
  lng: 127,
}

describe('홈 지도 레이어 상태', () => {
  it('기본값은 따릉이 레이어다', () => {
    const { result } = renderHook(() => useHomeMapLayers())
    expect(result.current.layer).toBe('bike')
    expect(result.current.selectedStation).toBeNull()
  })

  it('레이어를 끄면 선택한 대여소를 해제한다', () => {
    const { result } = renderHook(() => useHomeMapLayers())
    act(() => result.current.selectStation(station))
    expect(result.current.selectedStation).toBe(station)
    act(() => result.current.setLayer(null))
    expect(result.current.selectedStation).toBeNull()
    expect(result.current.layer).toBeNull()
  })

  it('대여소가 아닌 장소는 무시하고 clearStation으로 해제한다', () => {
    const { result } = renderHook(() => useHomeMapLayers())
    act(() => result.current.selectStation({ ...station, kind: '지하철역' }))
    expect(result.current.selectedStation).toBeNull()
    act(() => result.current.selectStation(station))
    act(() => result.current.clearStation())
    expect(result.current.selectedStation).toBeNull()
  })
})

describe('홈을 벗어날 때', () => {
  it('선택한 대여소를 해제하고 레이어는 유지한다', () => {
    const { result, rerender } = renderHook(({ active }) => useHomeMapLayers(active), {
      initialProps: { active: true },
    })
    act(() => result.current.selectStation(station))
    expect(result.current.selectedStation).toBe(station)
    rerender({ active: false })
    expect(result.current.selectedStation).toBeNull()
    expect(result.current.layer).toBe('bike')
    act(() => result.current.selectStation(station))
    expect(result.current.selectedStation).toBeNull()
  })
})
