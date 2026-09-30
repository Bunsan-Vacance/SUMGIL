// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useRerouteCheck } from './useRerouteCheck'
import { initialGuidance, type GuidanceState } from './guidanceReducer'
import type { RerouteCheckResponse, RerouteRepository } from '../../api/reroute'
import type { Route } from '../route/types'

afterEach(() => {
  vi.useRealTimers()
})

const baseRoute: Route = {
  id: 'r1',
  label: '경로',
  minutes: 18,
  transfers: 0,
  modes: ['walk', 'subway', 'walk', 'bike', 'walk'],
  legs: [
    {
      mode: 'walk',
      title: '역으로 이동',
      note: '',
      minutes: 3,
      from: { id: 'origin' },
      to: { id: 'yeoksam', lat: 37.5, lng: 127.0 },
    },
    {
      mode: 'subway',
      title: '지하철 이동',
      note: '',
      minutes: 5,
      from: { id: 'yeoksam', lat: 37.5, lng: 127.0 },
      to: { id: 'seolleung', lat: 37.504, lng: 127.048 },
    },
    {
      mode: 'walk',
      title: '대여소로 이동',
      note: '',
      minutes: 2,
      from: { id: 'ND-1', lat: 37.5045, lng: 127.049 },
      to: { id: 'rental-a', rentalId: 'ST-1', lat: 37.505, lng: 127.05 },
    },
    {
      mode: 'bike',
      title: '따릉이 이동',
      note: '',
      minutes: 6,
      from: { id: 'rental-a', rentalId: 'ST-1' },
      to: { id: 'rental-b', rentalId: 'ST-2' },
    },
    { mode: 'walk', title: '도착', note: '', minutes: 2 },
  ],
}

function makeState(overrides: Partial<GuidanceState> = {}): GuidanceState {
  return {
    ...initialGuidance,
    route: baseRoute,
    destination: { id: 'dogok', name: '도곡역', address: '', kind: '역', stationId: 'dogok' },
    step: 1,
    completed: false,
    ...overrides,
  }
}

function proposalResponse(recommendationId: string): RerouteCheckResponse {
  return {
    status: 'proposal',
    recommendationId,
    validUntil: '2999-01-01T00:00:00+09:00',
    recommendedBy: 'AGENT',
    reason: '대안 대여소가 더 여유로워요.',
    target: { rentalId: 'ST-1' },
    alternative: { rentalId: 'ST-2', lat: 37.5, lng: 127.0, distanceMeters: 50 },
    boundary: { legIndex: 2, nodeId: 'ND-1', lat: 37.5045, lng: 127.049 },
    walkLeg: {
      mode: 'WALK',
      fromLat: 37.5045,
      fromLng: 127.049,
      toLat: 37.5,
      toLng: 127.0,
      minutes: 1,
      geometryStatus: 'estimated',
    },
    route: { legs: [{ mode: 'BIKE', minutes: 5 }] },
  }
}

async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('useRerouteCheck', () => {
  it('enabled가 false면 조건을 만족해도 호출하지 않는다', () => {
    vi.useFakeTimers()
    const check = vi.fn(async () => proposalResponse('reco-off'))
    const repository: RerouteRepository = { check }
    const { unmount } = renderHook(() =>
      useRerouteCheck({
        state: makeState(),
        enabled: false,
        repository,
        onProposal: vi.fn(),
      }),
    )
    act(() => {
      vi.advanceTimersByTime(500_000)
    })
    expect(check).not.toHaveBeenCalled()
    unmount()
  })

  it('조건을 만족하면 즉시 1회 호출하고, 첫 체크포인트(하차 120초 전)에 다시 확인한다', () => {
    vi.useFakeTimers()
    const check = vi.fn(async () => ({ status: 'no_trigger', reason: 'below_threshold' }) as const)
    const repository: RerouteRepository = { check }
    const { unmount } = renderHook(() =>
      useRerouteCheck({
        state: makeState(),
        enabled: true,
        repository,
        onProposal: vi.fn(),
      }),
    )
    expect(check).toHaveBeenCalledTimes(1)
    // 지하철 5분 leg → 체크포인트는 3분 시점 하나뿐이다.
    act(() => {
      vi.advanceTimersByTime(179_000)
    })
    expect(check).toHaveBeenCalledTimes(1)
    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    expect(check).toHaveBeenCalledTimes(2)
    act(() => {
      vi.advanceTimersByTime(600_000)
    })
    expect(check).toHaveBeenCalledTimes(2)
    unmount()
  })

  it('step이 바뀌면 즉시 다시 확인하고 체크포인트를 새로 건다', () => {
    vi.useFakeTimers()
    const twoSubway: Route = {
      ...baseRoute,
      legs: [
        baseRoute.legs[0],
        { ...baseRoute.legs[1], minutes: 10 },
        { ...baseRoute.legs[1], minutes: 8 },
        ...baseRoute.legs.slice(2),
      ],
    }
    const check = vi.fn(async () => ({ status: 'no_trigger' }) as const)
    const repository: RerouteRepository = { check }
    const { rerender, unmount } = renderHook(
      ({ state }: { state: GuidanceState }) =>
        useRerouteCheck({ state, enabled: true, repository, onProposal: vi.fn() }),
      { initialProps: { state: makeState({ route: twoSubway, step: 1 }) } },
    )
    expect(check).toHaveBeenCalledTimes(1)

    rerender({ state: makeState({ route: twoSubway, step: 2 }) })
    expect(check).toHaveBeenCalledTimes(2)
    // 이전 step의 예약(8분 시점)은 정리되고 새 step 기준 6분 시점만 남는다.
    act(() => {
      vi.advanceTimersByTime(360_000)
    })
    expect(check).toHaveBeenCalledTimes(3)
    act(() => {
      vi.advanceTimersByTime(600_000)
    })
    expect(check).toHaveBeenCalledTimes(3)
    unmount()
  })

  it('언마운트하면 예약된 체크포인트를 정리한다', () => {
    vi.useFakeTimers()
    const check = vi.fn(async () => ({ status: 'no_trigger' }) as const)
    const repository: RerouteRepository = { check }
    const { unmount } = renderHook(() =>
      useRerouteCheck({ state: makeState(), enabled: true, repository, onProposal: vi.fn() }),
    )
    expect(vi.getTimerCount()).toBe(1)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
    expect(check).toHaveBeenCalledTimes(1)
  })

  it('같은 recommendationId는 한 번만 onProposal로 알린다', async () => {
    vi.useFakeTimers()
    const response = proposalResponse('reco-dup')
    const check = vi.fn(async () => response)
    const repository: RerouteRepository = { check }
    const onProposal = vi.fn()
    const { unmount } = renderHook(() =>
      useRerouteCheck({ state: makeState(), enabled: true, repository, onProposal }),
    )
    await flushMicrotasks()
    expect(onProposal).toHaveBeenCalledTimes(1)
    expect(onProposal).toHaveBeenCalledWith(response, 2)

    act(() => {
      vi.advanceTimersByTime(180_000)
    })
    await flushMicrotasks()
    expect(onProposal).toHaveBeenCalledTimes(1)
    unmount()
  })

  it('validUntil이 지난 제안은 알리지 않는다', async () => {
    vi.useFakeTimers()
    const response = { ...proposalResponse('reco-expired'), validUntil: '2000-01-01T00:00:00Z' }
    const check = vi.fn(async () => response)
    const repository: RerouteRepository = { check }
    const onProposal = vi.fn()
    const { unmount } = renderHook(() =>
      useRerouteCheck({ state: makeState(), enabled: true, repository, onProposal }),
    )
    await flushMicrotasks()
    expect(onProposal).not.toHaveBeenCalled()
    unmount()
  })

  it('조건이 깨지면(완료) 폴링을 정리하고 더 이상 호출하지 않는다', () => {
    vi.useFakeTimers()
    const check = vi.fn(async () => ({ status: 'no_trigger' }) as const)
    const repository: RerouteRepository = { check }
    const { rerender, unmount } = renderHook(
      ({ state }: { state: GuidanceState }) =>
        useRerouteCheck({ state, enabled: true, repository, onProposal: vi.fn() }),
      { initialProps: { state: makeState() } },
    )
    expect(check).toHaveBeenCalledTimes(1)

    rerender({ state: makeState({ completed: true }) })
    act(() => {
      vi.advanceTimersByTime(240_000)
    })
    expect(check).toHaveBeenCalledTimes(1)
    unmount()
  })
})
