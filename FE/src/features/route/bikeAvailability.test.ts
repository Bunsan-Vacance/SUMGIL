// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BikeStock } from '../../api/contracts'
import type { BikePrediction } from '../../api/bikePrediction'
import type { Route } from './types'
import {
  bikeRouteAvailabilityMessage,
  loadBikeRouteAvailability,
  useBikeRouteAvailability,
  type BikeAvailabilityRepositories,
} from './bikeAvailability'

const route: Route = {
  id: 'bike-route',
  label: '따릉이 경로',
  minutes: 14,
  transfers: 0,
  modes: ['walk', 'bike'],
  departedAt: '2026-09-24T08:30:00+09:00',
  legs: [
    { mode: 'walk', title: '대여소까지 이동', note: '', minutes: 3 },
    {
      mode: 'bike',
      title: '따릉이 이용',
      note: '',
      minutes: 8,
      from: { name: '출발 대여소', rentalId: 'ST-1' },
      to: { name: '도착 대여소', rentalId: 'ST-2' },
    },
  ],
}

const prediction: BikePrediction = {
  status: 'AVAILABLE',
  predictedBikes: 4,
  availabilityProbability: 0.8,
  predictedAt: '2026-09-24T08:31:00+09:00',
  arrivalTime: '2026-09-23T23:33:00.000Z',
  rentalId: 'ST-1',
  source: 'MODEL',
}

const stock = (overrides: Partial<BikeStock> = {}): BikeStock => ({
  rentalId: 'ST-1',
  availableBikes: 6,
  rackCount: 6,
  stockUpdatedAt: '2026-09-24T08:31:00+09:00',
  status: 'AVAILABLE',
  ...overrides,
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((yes) => {
    resolve = yes
  })
  return { promise, resolve }
}

function predictionFor(rentalId: string): BikePrediction {
  return { ...prediction, rentalId }
}

function routeWithIds(id: string, rentalId: string, returnRentalId: string): Route {
  return {
    ...route,
    id,
    legs: route.legs.map((leg) =>
      leg.mode === 'bike'
        ? {
            ...leg,
            from: { ...leg.from, rentalId },
            to: { ...leg.to, rentalId: returnRentalId },
          }
        : leg,
    ),
  }
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

function repositories(
  predictionValue: BikePrediction | null,
  sourceStock: BikeStock,
  returnStock: BikeStock,
) {
  return {
    prediction: predictionValue ? { prediction: vi.fn().mockResolvedValue(predictionValue) } : null,
    stock: {
      stock: vi.fn((rentalId: string) =>
        Promise.resolve(rentalId === 'ST-1' ? sourceStock : { ...returnStock, rentalId }),
      ),
    },
  }
}

describe('BIKE 경로 이용 가능 여부', () => {
  it('도착 시 대여 불가와 현재 대여 불가 문구를 구분한다', () => {
    const arrivalUnavailable = bikeRouteAvailabilityMessage('rental-unavailable')
    const currentUnavailable = bikeRouteAvailabilityMessage('rental-unavailable-current')

    expect(arrivalUnavailable).toContain('도착 시')
    expect(arrivalUnavailable).not.toContain('현재 대여 가능한')
    expect(currentUnavailable).toContain('현재 대여 가능한')
    expect(currentUnavailable).toContain('도착 시 이용 가능 여부는 확인이 필요해요')
  })

  it('도착 시 예측 0대는 대여 불가로 판정한다', async () => {
    const result = await loadBikeRouteAvailability(
      route,
      new AbortController().signal,
      repositories({ ...prediction, predictedBikes: 0 }, stock(), stock({ rentalId: 'ST-2' })),
    )
    expect(result.status).toBe('rental-unavailable')
  })

  it('도착 예측이 양수면 현재 재고 0대만으로 대여 불가로 단정하지 않는다', async () => {
    const result = await loadBikeRouteAvailability(
      route,
      new AbortController().signal,
      repositories(
        prediction,
        stock({ availableBikes: 0 }),
        stock({ rentalId: 'ST-2', availableBikes: 2, rackCount: 6 }),
      ),
    )
    expect(result.status).toBe('available')
  })

  it('도착 예측이 없을 때 최신 현재 재고 0대는 대여 불가로 판정한다', async () => {
    const result = await loadBikeRouteAvailability(
      route,
      new AbortController().signal,
      repositories(
        null,
        stock({ availableBikes: 0 }),
        stock({ rentalId: 'ST-2', availableBikes: 2, rackCount: 6 }),
      ),
    )
    expect(result.status).toBe('rental-unavailable-current')
  })

  it('반납 대여소의 자전거가 총 거치대 이상이면 혼잡으로 판정한다', async () => {
    const result = await loadBikeRouteAvailability(
      route,
      new AbortController().signal,
      repositories(null, stock(), stock({ rentalId: 'ST-2', availableBikes: 6, rackCount: 6 })),
    )
    expect(result.status).toBe('return-crowded')
    expect(bikeRouteAvailabilityMessage(result.status)).toContain('반납 대여소가 혼잡해요')
  })

  it('반납 자전거가 거치대보다 적으면 이용 가능으로 판정한다', async () => {
    const result = await loadBikeRouteAvailability(
      route,
      new AbortController().signal,
      repositories(
        prediction,
        stock(),
        stock({ rentalId: 'ST-2', availableBikes: 5, rackCount: 6 }),
      ),
    )
    expect(result.status).toBe('available')
  })

  it('STALE 0대와 rackCount 누락은 이용 가능 여부 미확인으로 둔다', async () => {
    const result = await loadBikeRouteAvailability(
      route,
      new AbortController().signal,
      repositories(
        prediction,
        stock({ availableBikes: 0, status: 'STALE' }),
        stock({ rentalId: 'ST-2', status: 'STALE', availableBikes: 6, rackCount: 6 }),
      ),
    )
    expect(result.status).toBe('unknown')
    expect(result.stockUpdatedAt).toBe('2026-09-24T08:31:00+09:00')
  })

  it('rackCount 0은 혼잡 판단에서 제외한다', async () => {
    const result = await loadBikeRouteAvailability(
      route,
      new AbortController().signal,
      repositories(
        prediction,
        stock(),
        stock({ rentalId: 'ST-2', availableBikes: 0, rackCount: 0 }),
      ),
    )
    expect(result.status).toBe('unknown')
  })

  it('반납 재고 저장소가 없으면 반납 가능 여부를 확인 불가로 둔다', async () => {
    const result = await loadBikeRouteAvailability(route, new AbortController().signal, {
      prediction: { prediction: vi.fn().mockResolvedValue(prediction) },
      stock: null,
    })
    expect(result.status).toBe('unknown')
    expect(bikeRouteAvailabilityMessage(result.status)).toContain('확인할 수 없어요')
  })

  it('자전거 경로 batch가 모두 끝날 때까지 checking을 유지하고 한 번에 결과를 노출한다', async () => {
    const predictionDeferred = deferred<BikePrediction>()
    const repository: BikeAvailabilityRepositories = {
      prediction: { prediction: vi.fn(() => predictionDeferred.promise) },
      stock: {
        stock: vi.fn((rentalId: string) => Promise.resolve(stock({ rentalId, availableBikes: 1 }))),
      },
    }
    const routes = [route]
    const { result } = renderHook(() => useBikeRouteAvailability(routes, repository))

    expect(result.current[route.id]?.status).toBe('checking')
    await act(async () => {
      predictionDeferred.resolve(prediction)
      await Promise.resolve()
      await Promise.resolve()
    })
    await waitFor(() => expect(result.current[route.id]?.status).toBe('available'))
  })

  it('10초 timeout은 완료된 경로를 보존하고 미완료 경로를 unknown으로 확정한다', async () => {
    vi.useFakeTimers()
    const first = routeWithIds('bike-route-first', 'ST-1', 'ST-2')
    const second = routeWithIds('bike-route-second', 'ST-3', 'ST-4')
    const routes = [first, second]
    const firstPrediction = deferred<BikePrediction>()
    const secondPrediction = deferred<BikePrediction>()
    const signals: AbortSignal[] = []
    const repository: BikeAvailabilityRepositories = {
      prediction: {
        prediction: vi.fn((rentalId: string, _arrivalTime: string, signal: AbortSignal) => {
          signals.push(signal)
          return rentalId === 'ST-1' ? firstPrediction.promise : secondPrediction.promise
        }),
      },
      stock: {
        stock: vi.fn((rentalId: string) => Promise.resolve(stock({ rentalId, availableBikes: 1 }))),
      },
    }
    const { result } = renderHook(() => useBikeRouteAvailability(routes, repository))

    await act(async () => {
      firstPrediction.resolve(predictionFor('ST-1'))
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })
    act(() => vi.advanceTimersByTime(10_000))
    expect(result.current[first.id]?.status).toBe('available')
    expect(result.current[second.id]?.status).toBe('unknown')
    expect(signals.every((signal) => signal.aborted)).toBe(true)

    await act(async () => {
      secondPrediction.resolve(predictionFor('ST-3'))
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(result.current[second.id]?.status).toBe('unknown')
  })

  it('같은 route id의 새 batch에는 이전 availability를 노출하지 않는다', async () => {
    const oldPrediction = deferred<BikePrediction>()
    const newPrediction = deferred<BikePrediction>()
    const oldRepository: BikeAvailabilityRepositories = {
      prediction: { prediction: vi.fn(() => oldPrediction.promise) },
      stock: {
        stock: vi.fn((rentalId: string) => Promise.resolve(stock({ rentalId, availableBikes: 1 }))),
      },
    }
    const newRepository: BikeAvailabilityRepositories = {
      prediction: { prediction: vi.fn(() => newPrediction.promise) },
      stock: {
        stock: vi.fn((rentalId: string) => Promise.resolve(stock({ rentalId, availableBikes: 1 }))),
      },
    }
    const { result, rerender } = renderHook(
      ({ routes, repositories }) => useBikeRouteAvailability(routes, repositories),
      { initialProps: { routes: [route], repositories: oldRepository } },
    )

    await act(async () => {
      oldPrediction.resolve(prediction)
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })
    await waitFor(() => expect(result.current[route.id]?.status).toBe('available'))

    rerender({
      routes: [{ ...route, departedAt: '2026-09-25T08:30:00+09:00' }],
      repositories: newRepository,
    })
    expect(result.current[route.id]?.status).toBe('checking')
    await act(async () => {
      newPrediction.resolve(prediction)
      await Promise.resolve()
      await Promise.resolve()
    })
    await waitFor(() => expect(result.current[route.id]?.status).toBe('available'))
  })
})
