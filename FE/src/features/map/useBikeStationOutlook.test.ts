// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BikePrediction } from '../../api/bikePrediction'
import type { BikeStock } from '../../api/contracts'
import { useBikeStationOutlook } from './useBikeStationOutlook'

afterEach(cleanup)

const fixedNow = () => new Date('2026-10-09T01:00:00.000Z')
const stockOf = (rentalId: string, availableBikes: number | null = 5): BikeStock => ({
  rentalId,
  availableBikes,
  stockUpdatedAt: '2026-10-09T09:59:00+09:00',
  status: 'AVAILABLE',
})
const predictionOf = (rentalId: string, arrivalTime: string): BikePrediction => ({
  status: 'AVAILABLE',
  predictedBikes: 3,
  availabilityProbability: 0.8,
  predictedAt: '2026-10-09T10:00:00+09:00',
  arrivalTime,
  rentalId,
  source: 'MODEL',
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function okRepositories() {
  const stock = vi.fn(async (rentalId: string, _signal?: AbortSignal) => stockOf(rentalId))
  const prediction = vi.fn(async (rentalId: string, arrivalTime: string, _signal?: AbortSignal) =>
    predictionOf(rentalId, arrivalTime),
  )
  return { stock, prediction, stockRepo: { stock }, predictionRepo: { prediction } }
}

describe('대여소 재고·예측 조회', () => {
  it('rentalId가 없으면 모두 unavailable이고 요청하지 않는다', () => {
    const { stock, prediction, stockRepo, predictionRepo } = okRepositories()
    const { result } = renderHook(() =>
      useBikeStationOutlook(null, stockRepo, predictionRepo, fixedNow),
    )
    expect(result.current.stock.status).toBe('unavailable')
    expect(result.current.predictions.in15.status).toBe('unavailable')
    expect(result.current.predictions.in30.status).toBe('unavailable')
    expect(stock).not.toHaveBeenCalled()
    expect(prediction).not.toHaveBeenCalled()
  })

  it('재고와 두 시점 예측을 병렬로 조회하고 도착 시각을 now 기준으로 만든다', async () => {
    const { prediction, stockRepo, predictionRepo } = okRepositories()
    const { result } = renderHook(() =>
      useBikeStationOutlook('ST-1', stockRepo, predictionRepo, fixedNow),
    )
    expect(result.current.stock.status).toBe('loading')
    await waitFor(() => expect(result.current.predictions.in30.status).toBe('success'))
    expect(result.current.stock.status).toBe('success')
    expect(result.current.predictions.in15.status).toBe('success')
    expect(prediction).toHaveBeenCalledWith(
      'ST-1',
      '2026-10-09T01:15:00.000Z',
      expect.any(AbortSignal),
    )
    expect(prediction).toHaveBeenCalledWith(
      'ST-1',
      '2026-10-09T01:30:00.000Z',
      expect.any(AbortSignal),
    )
  })

  it('재고 오류와 예측 오류는 서로 독립이다', async () => {
    const { predictionRepo } = okRepositories()
    const stockRepo = { stock: vi.fn(async () => Promise.reject(new Error('boom'))) }
    const first = renderHook(() =>
      useBikeStationOutlook('ST-1', stockRepo, predictionRepo, fixedNow),
    )
    await waitFor(() => expect(first.result.current.stock.status).toBe('error'))
    await waitFor(() => expect(first.result.current.predictions.in15.status).toBe('success'))

    const failing = {
      prediction: vi.fn(async (_id: string, arrival: string) =>
        arrival.includes('01:15')
          ? Promise.reject(new Error('boom'))
          : predictionOf('ST-1', arrival),
      ),
    }
    const okStock = { stock: async () => stockOf('ST-1') }
    const second = renderHook(() => useBikeStationOutlook('ST-1', okStock, failing, fixedNow))
    await waitFor(() => expect(second.result.current.predictions.in15.status).toBe('error'))
    await waitFor(() => expect(second.result.current.predictions.in30.status).toBe('success'))
    expect(second.result.current.stock.status).toBe('success')
  })

  it('대여소가 바뀌면 이전 요청을 취소하고 늦은 응답을 무시한다', async () => {
    const slow = deferred<BikeStock>()
    const signals: AbortSignal[] = []
    const stockRepo = {
      stock: vi.fn((rentalId: string, signal: AbortSignal) => {
        signals.push(signal)
        return rentalId === 'ST-1' ? slow.promise : Promise.resolve(stockOf(rentalId, 9))
      }),
    }
    const { result, rerender } = renderHook(
      ({ id }) => useBikeStationOutlook(id, stockRepo, null, fixedNow),
      { initialProps: { id: 'ST-1' } },
    )
    rerender({ id: 'ST-2' })
    expect(signals[0].aborted).toBe(true)
    await waitFor(() => expect(result.current.stock.status).toBe('success'))
    await act(async () => {
      slow.resolve(stockOf('ST-1', 1))
      await slow.promise
    })
    expect(result.current.stock).toMatchObject({
      status: 'success',
      value: { rentalId: 'ST-2', availableBikes: 9 },
    })
  })

  it('저장소가 없으면 해당 항목만 unavailable이다', async () => {
    const { stockRepo, predictionRepo } = okRepositories()
    const noStock = renderHook(() => useBikeStationOutlook('ST-1', null, predictionRepo, fixedNow))
    expect(noStock.result.current.stock.status).toBe('unavailable')
    await waitFor(() => expect(noStock.result.current.predictions.in15.status).toBe('success'))
    const noPrediction = renderHook(() => useBikeStationOutlook('ST-1', stockRepo, null, fixedNow))
    expect(noPrediction.result.current.predictions.in15.status).toBe('unavailable')
    await waitFor(() => expect(noPrediction.result.current.stock.status).toBe('success'))
  })

  it('retry는 loading을 거쳐 다시 조회한다', async () => {
    const { stock, stockRepo, predictionRepo } = okRepositories()
    const { result } = renderHook(() =>
      useBikeStationOutlook('ST-1', stockRepo, predictionRepo, fixedNow),
    )
    await waitFor(() => expect(result.current.stock.status).toBe('success'))
    act(() => result.current.retry())
    expect(result.current.stock.status).toBe('loading')
    expect(result.current.predictions.in15.status).toBe('loading')
    await waitFor(() => expect(result.current.stock.status).toBe('success'))
    expect(stock).toHaveBeenCalledTimes(2)
  })

  it('UNAVAILABLE 응답도 success로 보존한다', async () => {
    const stockRepo = {
      stock: async () => ({
        rentalId: 'ST-1',
        availableBikes: null,
        stockUpdatedAt: null,
        status: 'UNAVAILABLE' as const,
      }),
    }
    const predictionRepo = {
      prediction: async (rentalId: string, arrivalTime: string) => ({
        ...predictionOf(rentalId, arrivalTime),
        status: 'UNAVAILABLE' as const,
        predictedBikes: null,
        availabilityProbability: null,
      }),
    }
    const { result } = renderHook(() =>
      useBikeStationOutlook('ST-1', stockRepo, predictionRepo, fixedNow),
    )
    await waitFor(() => expect(result.current.predictions.in30.status).toBe('success'))
    expect(result.current.stock).toMatchObject({
      status: 'success',
      value: { status: 'UNAVAILABLE' },
    })
    expect(result.current.predictions.in15).toMatchObject({
      status: 'success',
      value: { status: 'UNAVAILABLE' },
    })
  })
})
