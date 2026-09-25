// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { places, routes } from '../../api/mock/fixtures'
import { GUIDANCE_STORAGE_KEY, useGuidance } from './useGuidance'

const originalGeolocation = Object.getOwnPropertyDescriptor(navigator, 'geolocation')
const originalPermissions = Object.getOwnPropertyDescriptor(navigator, 'permissions')

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  if (originalGeolocation) Object.defineProperty(navigator, 'geolocation', originalGeolocation)
  else Reflect.deleteProperty(navigator, 'geolocation')
  if (originalPermissions) Object.defineProperty(navigator, 'permissions', originalPermissions)
  else Reflect.deleteProperty(navigator, 'permissions')
})

describe('길안내 위치 추적', () => {
  beforeEach(() => sessionStorage.clear())

  it('저장된 GPS 후보는 복원하지 않고 다시 저장할 때도 제외한다', async () => {
    sessionStorage.setItem(
      GUIDANCE_STORAGE_KEY,
      JSON.stringify({
        route: routes[0],
        step: 0,
        completed: false,
        locationCandidateStep: 0,
        locationCandidateCount: 1,
        transitAwayStep: 0,
        position: { latitude: 37.5, longitude: 127, accuracy: 5 },
      }),
    )
    const { result } = renderHook(() => useGuidance(false))
    expect(result.current.step).toBe(0)
    const stored = JSON.parse(sessionStorage.getItem(GUIDANCE_STORAGE_KEY)!)
    expect(stored.locationCandidateStep).toBeUndefined()
    expect(stored.locationCandidateCount).toBeUndefined()
    expect(stored.transitAwayStep).toBeUndefined()
    expect(stored.position).toBeUndefined()
    expect(result.current.position).toBeNull()
  })

  it('안내가 끝나면 위치 추적을 정리한다', async () => {
    const clearWatch = vi.fn()
    const watchPosition = vi.fn(() => 7)
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { watchPosition, clearWatch },
    })
    const rendered = renderHook(() => useGuidance(true))

    act(() => rendered.result.current.start(routes[0], places[0], places[1]))
    await waitFor(() => expect(watchPosition).toHaveBeenCalledOnce())

    rendered.unmount()
    expect(clearWatch).toHaveBeenCalledWith(7)
  })

  it('권한 거부 상태에서 재시도하면 위치 추적을 다시 시작한다', async () => {
    const watchPosition = vi
      .fn()
      .mockImplementationOnce((_success, error) => {
        error({ code: 2 } as GeolocationPositionError)
        return 1
      })
      .mockImplementationOnce((_success, error) => {
        error({ code: 1 } as GeolocationPositionError)
        return 2
      })
      .mockImplementationOnce((success) => {
        const position = {
          timestamp: Date.now() - 100,
          coords: {
            latitude: routes[0].legs[0].to!.lat,
            longitude: routes[0].legs[0].to!.lng,
            accuracy: 5,
          },
        } as GeolocationPosition
        success(position)
        success({ ...position, timestamp: Date.now() })
        return 3
      })
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { watchPosition, clearWatch: vi.fn() },
    })
    const rendered = renderHook(() => useGuidance(true))

    act(() => rendered.result.current.start(routes[0], places[0], places[1]))
    await waitFor(() => expect(rendered.result.current.locationStatus).toBe('no-position'))

    act(() => rendered.result.current.retryLocation())
    await waitFor(() => expect(watchPosition).toHaveBeenCalledTimes(2))
    expect(rendered.result.current.locationStatus).toBe('denied')

    act(() => rendered.result.current.retryLocation())
    await waitFor(() => expect(watchPosition).toHaveBeenCalledTimes(3))
    expect(rendered.result.current.locationStatus).toBe('tracking')
    expect(rendered.result.current.step).toBe(1)
  })

  it('권한이 거부에서 허용으로 바뀌면 자동으로 watch를 다시 시작한다', async () => {
    let permissionChange!: () => void
    const permissionState = {
      state: 'denied',
      addEventListener: vi.fn((_type: string, listener: () => void) => {
        permissionChange = listener
      }),
      removeEventListener: vi.fn(),
    }
    const permission = permissionState as unknown as PermissionStatus
    const watchPosition = vi.fn((_success, error) => {
      error({ code: 1 } as GeolocationPositionError)
      return watchPosition.mock.calls.length
    })
    const clearWatch = vi.fn()
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { watchPosition, clearWatch },
    })
    Object.defineProperty(navigator, 'permissions', {
      configurable: true,
      value: { query: vi.fn(async () => permission) },
    })
    const rendered = renderHook(() => useGuidance(true))

    act(() => rendered.result.current.start(routes[0], places[0], places[1]))
    await waitFor(() => expect(rendered.result.current.locationStatus).toBe('denied'))
    expect(permission.addEventListener).toHaveBeenCalledWith('change', expect.any(Function))

    permissionState.state = 'granted'
    act(() => permissionChange())
    await waitFor(() => expect(watchPosition).toHaveBeenCalledTimes(2))
    expect(clearWatch).toHaveBeenCalledWith(1)
  })

  it('화면을 나간 뒤 늦게 온 위치 응답을 무시하고 watch를 해제한다', async () => {
    const clearWatch = vi.fn()
    let success!: (position: GeolocationPosition) => void
    const watchPosition = vi.fn((onSuccess: (position: GeolocationPosition) => void) => {
      success = onSuccess
      return 9
    })
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { watchPosition, clearWatch },
    })
    const rendered = renderHook(({ enabled }) => useGuidance(enabled), {
      initialProps: { enabled: true },
    })

    act(() => rendered.result.current.start(routes[0], places[0], places[1]))
    await waitFor(() => expect(watchPosition).toHaveBeenCalledOnce())
    rendered.rerender({ enabled: false })
    await waitFor(() => expect(clearWatch).toHaveBeenCalledWith(9))

    act(() =>
      success({
        timestamp: Date.now(),
        coords: {
          latitude: routes[0].legs[0].to!.lat,
          longitude: routes[0].legs[0].to!.lng,
          accuracy: 5,
        },
      } as GeolocationPosition),
    )
    expect(rendered.result.current.step).toBe(0)
  })

  it('위치 하나를 지도와 안내에 공유하고 캐시 중복·오래된 위치·낮은 정확도로 넘기지 않는다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-25T10:00:00Z'))
    let success!: (position: GeolocationPosition) => void
    let failure!: (error: GeolocationPositionError) => void
    const clearWatch = vi.fn()
    const watchPosition = vi.fn((onSuccess, onError) => {
      success = onSuccess
      failure = onError
      return 10
    })
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { watchPosition, clearWatch },
    })
    const { result, rerender } = renderHook(({ enabled }) => useGuidance(enabled), {
      initialProps: { enabled: true },
    })
    act(() => result.current.start(routes[0], places[0], places[1]))
    const endpoint = routes[0].legs[0].to!
    const fix = (accuracy = 5, timestamp = Date.now()) =>
      ({
        timestamp,
        coords: { latitude: endpoint.lat!, longitude: endpoint.lng!, accuracy },
      }) as GeolocationPosition
    act(() => success(fix()))
    expect(result.current.position).toEqual(fix().coords)
    act(() => success(fix()))
    expect(result.current.step).toBe(0)
    act(() => vi.advanceTimersByTime(1_000))
    act(() => success(fix(80)))
    expect(result.current).toMatchObject({ position: null, locationStatus: 'inaccurate', step: 0 })
    act(() => vi.advanceTimersByTime(1_000))
    act(() => success(fix()))
    expect(result.current.step).toBe(0)
    act(() => vi.advanceTimersByTime(15_001))
    expect(result.current).toMatchObject({ position: null, locationStatus: 'no-position' })
    act(() => success(fix(5, Date.now() - 60_000)))
    expect(result.current.step).toBe(0)
    act(() => success(fix()))
    expect(result.current.step).toBe(0)
    act(() => vi.advanceTimersByTime(1_000))
    act(() => success(fix()))
    expect(result.current.step).toBe(1)
    expect(watchPosition).toHaveBeenCalledOnce()
    expect(JSON.parse(sessionStorage.getItem(GUIDANCE_STORAGE_KEY)!).position).toBeUndefined()
    act(() => failure({ code: 1 } as GeolocationPositionError))
    expect(result.current).toMatchObject({ position: null, locationStatus: 'denied' })
    rerender({ enabled: false })
    expect(clearWatch).toHaveBeenCalledWith(10)
  })
})
