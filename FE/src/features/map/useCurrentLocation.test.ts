// @vitest-environment jsdom

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCurrentLocation } from './useCurrentLocation'

const position = {
  coords: { latitude: 37.5, longitude: 127.03 },
} as GeolocationPosition

let originalDescriptor: PropertyDescriptor | undefined

beforeEach(() => {
  originalDescriptor = Object.getOwnPropertyDescriptor(navigator, 'geolocation')
})

afterEach(() => {
  cleanup()
  if (originalDescriptor) Object.defineProperty(navigator, 'geolocation', originalDescriptor)
  else Reflect.deleteProperty(navigator, 'geolocation')
})

describe('현재 위치 요청', () => {
  it('버튼을 눌렀을 때만 위치를 요청하고 성공 좌표를 전달한다', () => {
    const getCurrentPosition = vi.fn()
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition },
    })
    const onPosition = vi.fn()
    const { result } = renderHook(() => useCurrentLocation(onPosition, vi.fn(), 'search'))

    expect(getCurrentPosition).not.toHaveBeenCalled()
    act(() => result.current.locate())
    expect(getCurrentPosition).toHaveBeenCalledOnce()
    expect(result.current.locating).toBe(true)

    act(() => getCurrentPosition.mock.calls[0][0](position))
    expect(result.current.locating).toBe(false)
    expect(onPosition).toHaveBeenCalledWith(position)
  })

  it('위치 권한 거부를 안내한다', () => {
    const getCurrentPosition = vi.fn()
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition },
    })
    const onMessage = vi.fn()
    const { result } = renderHook(() => useCurrentLocation(vi.fn(), onMessage, 'search'))

    act(() => result.current.locate())
    act(() => getCurrentPosition.mock.calls[0][1]({ code: 1 } as GeolocationPositionError))

    expect(result.current.locating).toBe(false)
    expect(onMessage).toHaveBeenCalledWith('현재 위치를 보려면 위치 권한을 허용해 주세요.')
  })

  it('검색 대상이 바뀌면 늦게 도착한 위치를 무시한다', () => {
    const getCurrentPosition = vi.fn()
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition },
    })
    const onPosition = vi.fn()
    const { result, rerender } = renderHook(
      ({ scope }) => useCurrentLocation(onPosition, vi.fn(), scope),
      { initialProps: { scope: 'origin-search' } },
    )

    act(() => result.current.locate())
    rerender({ scope: 'origin-map' })
    act(() => getCurrentPosition.mock.calls[0][0](position))

    expect(onPosition).not.toHaveBeenCalled()
  })
})
