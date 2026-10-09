// @vitest-environment jsdom

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TrainArrivalResult } from '../../api/guidance'
import { useStationArrivals } from './useStationArrivals'

const NOW = new Date('2026-10-09T01:00:00.000Z')
const now = () => NOW

const resultOf = (minutes: number): TrainArrivalResult => ({
  status: 'LIVE',
  updatedAt: NOW.toISOString(),
  trains: [
    {
      trainId: 't1',
      direction: '내선',
      arrivalTime: new Date(NOW.getTime() + minutes * 60000).toISOString(),
      updatedAt: NOW.toISOString(),
      source: 'LIVE',
    },
  ],
})

function setVisibility(value: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => value })
}

beforeEach(() => {
  vi.useFakeTimers()
  setVisibility('visible')
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  setVisibility('visible')
})

const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)))
const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)))

describe('역 실시간 도착 조회', () => {
  it('최초 조회는 loading을 거쳐 success와 방면별 도착 정보를 만든다', async () => {
    const arrivals = vi.fn(async () => resultOf(3))
    const { result } = renderHook(() =>
      useStationArrivals('222', '1002', '강남', '2호선', { arrivals }, 30_000, now),
    )
    expect(result.current.status).toBe('loading')
    await flush()
    expect(result.current.status).toBe('success')
    expect(result.current.directions[0]).toMatchObject({ direction: '내선' })
    expect(result.current.directions[0].trains[0].etaMinutes).toBe(3)
    expect(result.current.fetchedAt).toBe(NOW.toISOString())
    expect(arrivals).toHaveBeenCalledWith(
      { stationId: '222', routeId: '1002', stationName: '강남', routeName: '2호선' },
      expect.any(AbortSignal),
    )
  })

  it('lineId가 없으면 unsupported이고 요청하지 않는다', async () => {
    const arrivals = vi.fn(async () => resultOf(3))
    const { result } = renderHook(() =>
      useStationArrivals('222', null, '강남', null, { arrivals }, 30_000, now),
    )
    await flush()
    expect(result.current.status).toBe('unsupported')
    expect(arrivals).not.toHaveBeenCalled()
    const noRepository = renderHook(() =>
      useStationArrivals('222', '1002', '강남', '2호선', null, 30_000, now),
    )
    expect(noRepository.result.current.status).toBe('unsupported')
  })

  it('오류가 나면 error이고 이전 결과는 유지한다', async () => {
    const arrivals = vi
      .fn()
      .mockResolvedValueOnce(resultOf(3))
      .mockRejectedValueOnce(new Error('boom'))
    const { result } = renderHook(() =>
      useStationArrivals('222', '1002', '강남', '2호선', { arrivals }, 30_000, now),
    )
    await flush()
    await advance(30_000)
    expect(result.current.status).toBe('error')
    expect(result.current.result).not.toBeNull()
    expect(result.current.directions).toHaveLength(1)
  })

  it('노선이 바뀌면 이전 요청을 취소하고 다시 조회한다', async () => {
    const signals: AbortSignal[] = []
    const arrivals = vi.fn((_request: unknown, signal: AbortSignal) => {
      signals.push(signal)
      return new Promise<TrainArrivalResult>(() => {})
    })
    const { rerender } = renderHook(
      ({ line }) => useStationArrivals('222', line, '강남', null, { arrivals }, 30_000, now),
      { initialProps: { line: '1002' } },
    )
    rerender({ line: '1007' })
    expect(signals[0].aborted).toBe(true)
    expect(arrivals).toHaveBeenCalledTimes(2)
    expect(arrivals.mock.calls[1][0]).toMatchObject({ routeId: '1007' })
  })

  it('30초마다 재조회하되 탭이 숨겨져 있으면 건너뛰고 status는 유지한다', async () => {
    const arrivals = vi.fn(async () => resultOf(3))
    const { result } = renderHook(() =>
      useStationArrivals('222', '1002', '강남', '2호선', { arrivals }, 30_000, now),
    )
    await flush()
    await advance(30_000)
    expect(arrivals).toHaveBeenCalledTimes(2)
    expect(result.current.status).toBe('success')
    setVisibility('hidden')
    await advance(30_000)
    expect(arrivals).toHaveBeenCalledTimes(2)
    setVisibility('visible')
    await advance(30_000)
    expect(arrivals).toHaveBeenCalledTimes(3)
  })

  it('재조회 중에도 status는 success를 유지한다', async () => {
    let resolve!: (value: TrainArrivalResult) => void
    const arrivals = vi
      .fn()
      .mockResolvedValueOnce(resultOf(3))
      .mockImplementationOnce(
        () =>
          new Promise<TrainArrivalResult>((res) => {
            resolve = res
          }),
      )
    const { result } = renderHook(() =>
      useStationArrivals('222', '1002', '강남', '2호선', { arrivals }, 30_000, now),
    )
    await flush()
    await advance(30_000)
    expect(result.current.status).toBe('success')
    await act(async () => resolve(resultOf(5)))
    expect(result.current.directions[0].trains[0].etaMinutes).toBe(5)
  })

  it('retry는 loading을 거쳐 다시 조회한다', async () => {
    const arrivals = vi.fn(async () => resultOf(3))
    const { result } = renderHook(() =>
      useStationArrivals('222', '1002', '강남', '2호선', { arrivals }, 30_000, now),
    )
    await flush()
    act(() => result.current.retry())
    expect(result.current.status).toBe('loading')
    await flush()
    expect(result.current.status).toBe('success')
    expect(arrivals).toHaveBeenCalledTimes(2)
  })

  it('언마운트하면 요청을 취소하고 타이머를 해제한다', async () => {
    const signals: AbortSignal[] = []
    const arrivals = vi.fn((_request: unknown, signal: AbortSignal) => {
      signals.push(signal)
      return Promise.resolve(resultOf(3))
    })
    const { unmount } = renderHook(() =>
      useStationArrivals('222', '1002', '강남', '2호선', { arrivals }, 30_000, now),
    )
    await flush()
    unmount()
    expect(signals[0].aborted).toBe(true)
    await advance(60_000)
    expect(arrivals).toHaveBeenCalledTimes(1)
  })
})
