// @vitest-environment jsdom

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { OpsRepository } from '../../api/contracts'
import { RepositoryError } from '../../api/errors'
import type { BikeStockOverview, CongestionHeatmap, OpsResult } from './types'
import { OPS_POLL_MS, useOpsData } from './useOpsData'

const stock: BikeStockOverview = {
  arrivalTime: null,
  count: 1,
  truncated: false,
  generatedAt: null,
  items: [
    {
      rentalId: 'ST-1',
      name: 'a',
      lat: 37.5,
      lng: 127,
      rackCount: 10,
      availableBikes: 0,
      stockStatus: 'AVAILABLE',
      stockUpdatedAt: null,
      predictedBikes: null,
      availabilityProbability: null,
      predictionStatus: 'UNAVAILABLE',
      predictionSource: null,
      predictedAt: null,
    },
  ],
}
const heatmap: CongestionHeatmap = {
  date: '2026-10-03',
  source: 'congestion_pred',
  generatedAt: null,
  predictorVersions: [],
  slotFrom: 10,
  slotTo: 47,
  lines: [{ lineId: '1', lineName: '1호선', cells: [] }],
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

const okStock = (data = stock): OpsResult<BikeStockOverview> => ({ source: 'api', data })
const okHeatmap = (data = heatmap): OpsResult<CongestionHeatmap> => ({ source: 'mock', data })

function makeRepository(overrides: Partial<OpsRepository> = {}): OpsRepository {
  return {
    bikeStockOverview: vi.fn().mockResolvedValue(okStock()),
    congestionHeatmap: vi.fn().mockResolvedValue(okHeatmap()),
    ...overrides,
  }
}

const setVisibility = (state: 'visible' | 'hidden') => {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
}

beforeEach(() => {
  vi.useFakeTimers()
  setVisibility('visible')
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('운영자 뷰 조회 상태', () => {
  it('loading → ready로 바뀌고 source를 보존한다', async () => {
    const repository = makeRepository()
    const { result } = renderHook(() => useOpsData({ repository }))
    expect(result.current.stock.status).toBe('loading')
    await act(async () => {})
    expect(result.current.stock).toMatchObject({ status: 'ready', source: 'api' })
    expect(result.current.stock.data?.items[0].availableBikes).toBe(0)
    expect(result.current.heatmap).toMatchObject({ status: 'ready', source: 'mock' })
  })

  it('성공한 빈 결과는 empty, 실패는 error로 구분한다', async () => {
    const repository = makeRepository({
      bikeStockOverview: vi.fn().mockResolvedValue(okStock({ ...stock, items: [], count: 0 })),
      congestionHeatmap: vi
        .fn()
        .mockRejectedValue(new RepositoryError('network', '서버에 연결하지 못했어요.')),
    })
    const { result } = renderHook(() => useOpsData({ repository }))
    await act(async () => {})
    expect(result.current.stock.status).toBe('empty')
    expect(result.current.heatmap).toMatchObject({
      status: 'error',
      error: '서버에 연결하지 못했어요.',
    })
    expect(result.current.heatmap.data).toBeUndefined()
  })

  it('저장소가 없으면 mock으로 대체하지 않고 오류 상태가 된다', async () => {
    const { result } = renderHook(() => useOpsData({ repository: null }))
    await act(async () => {})
    expect(result.current.stock.status).toBe('error')
    expect(result.current.heatmap.status).toBe('error')
  })

  it('언마운트하면 진행 중 요청을 중단하고 늦은 응답은 무시한다', async () => {
    const pending = deferred<OpsResult<BikeStockOverview>>()
    let signal: AbortSignal | undefined
    const repository = makeRepository({
      bikeStockOverview: vi.fn((_request, s: AbortSignal) => {
        signal = s
        return pending.promise
      }),
    })
    const { result, unmount } = renderHook(() => useOpsData({ repository }))
    await act(async () => {})
    expect(signal?.aborted).toBe(false)
    unmount()
    expect(signal?.aborted).toBe(true)
    pending.resolve(okStock())
    await act(async () => {})
    expect(result.current.stock.status).toBe('loading')
  })

  it('새 요청이 시작되면 이전 요청의 늦은 응답은 반영하지 않는다', async () => {
    const first = deferred<OpsResult<BikeStockOverview>>()
    const second = deferred<OpsResult<BikeStockOverview>>()
    const fn = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const repository = makeRepository({ bikeStockOverview: fn })
    const { result } = renderHook(() => useOpsData({ repository }))
    await act(async () => {})
    act(() => result.current.refreshStock())
    expect(fn).toHaveBeenCalledTimes(2)
    second.resolve(okStock({ ...stock, generatedAt: 'second' }))
    await act(async () => {})
    first.resolve(okStock({ ...stock, generatedAt: 'first' }))
    await act(async () => {})
    expect(result.current.stock.data?.generatedAt).toBe('second')
  })

  it('60초마다 폴링하되 탭이 숨겨져 있으면 건너뛴다', async () => {
    const repository = makeRepository()
    renderHook(() => useOpsData({ repository }))
    await act(async () => {})
    const stockMock = repository.bikeStockOverview as ReturnType<typeof vi.fn>
    expect(stockMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPS_POLL_MS)
    })
    expect(stockMock).toHaveBeenCalledTimes(2)

    act(() => setVisibility('hidden'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPS_POLL_MS * 3)
    })
    expect(stockMock).toHaveBeenCalledTimes(2)

    // 다시 보이면 마지막 조회 후 한 주기 이상 지났으므로 즉시 갱신한다.
    act(() => setVisibility('visible'))
    await act(async () => {})
    expect(stockMock).toHaveBeenCalledTimes(3)
  })

  it('폴링 중에는 이전 결과를 로딩 표시로 지우지 않는다', async () => {
    const repository = makeRepository()
    const { result } = renderHook(() => useOpsData({ repository }))
    await act(async () => {})
    const next = deferred<OpsResult<BikeStockOverview>>()
    ;(repository.bikeStockOverview as ReturnType<typeof vi.fn>).mockReturnValueOnce(next.promise)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPS_POLL_MS)
    })
    expect(result.current.stock.status).toBe('ready')
  })
})

describe('지도 bbox 연동', () => {
  const boundsA = { sw: { lat: 37.5, lng: 126.9 }, ne: { lat: 37.6, lng: 127.0 } }
  const boundsB = { sw: { lat: 37.4, lng: 126.8 }, ne: { lat: 37.5, lng: 126.9 } }

  it('bbox가 바뀌면 재고를 다시 조회하고 이전 요청을 중단한다', async () => {
    const signals: AbortSignal[] = []
    const first = deferred<OpsResult<BikeStockOverview>>()
    const fn = vi
      .fn()
      .mockImplementationOnce((_request, s: AbortSignal) => {
        signals.push(s)
        return first.promise
      })
      .mockImplementation((_request, s: AbortSignal) => {
        signals.push(s)
        return Promise.resolve(okStock({ ...stock, generatedAt: 'B' }))
      })
    const repository = makeRepository({ bikeStockOverview: fn })
    const { result, rerender } = renderHook(({ bounds }) => useOpsData({ repository, bounds }), {
      initialProps: { bounds: boundsA },
    })
    await act(async () => {})
    expect(fn).toHaveBeenCalledTimes(1)
    expect(fn.mock.calls[0][0]).toMatchObject({ sw: boundsA.sw, ne: boundsA.ne })

    rerender({ bounds: boundsB })
    await act(async () => {})
    expect(fn).toHaveBeenCalledTimes(2)
    expect(fn.mock.calls[1][0]).toMatchObject({ sw: boundsB.sw, ne: boundsB.ne })
    expect(signals[0].aborted).toBe(true)

    first.resolve(okStock({ ...stock, generatedAt: 'A' }))
    await act(async () => {})
    expect(result.current.stock.data?.generatedAt).toBe('B')
  })

  it('같은 값의 새 bounds 객체로는 다시 조회하지 않는다', async () => {
    const repository = makeRepository()
    const { rerender } = renderHook(({ bounds }) => useOpsData({ repository, bounds }), {
      initialProps: { bounds: boundsA },
    })
    await act(async () => {})
    rerender({ bounds: { sw: { ...boundsA.sw }, ne: { ...boundsA.ne } } })
    await act(async () => {})
    expect(repository.bikeStockOverview).toHaveBeenCalledTimes(1)
  })
})
