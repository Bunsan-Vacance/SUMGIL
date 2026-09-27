// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import type { BikePrediction } from '../api/bikePrediction'
import type { BikeStock } from '../api/contracts'
import type { Mode, Route } from '../features/route/types'
import { places } from '../api/mock/fixtures'
import ResultsPage from './ResultsPage'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

const requests = vi.hoisted(() => ({
  prediction: null as {
    promise: Promise<BikePrediction>
    resolve: (value: BikePrediction) => void
  } | null,
  stocks: [] as Array<{
    rentalId: string
    deferred: { promise: Promise<BikeStock>; resolve: (value: BikeStock) => void }
  }>,
}))

vi.mock('../api/repositories', () => ({
  bikePredictionRepository: {
    prediction: () => {
      const next = deferred<BikePrediction>()
      requests.prediction = next
      return next.promise
    },
  },
  bikeStockRepository: {
    stock: (rentalId: string) => {
      const next = deferred<BikeStock>()
      requests.stocks.push({ rentalId, deferred: next })
      return next.promise
    },
  },
  isBikeStockMockEnabled: false,
}))

function props(overrides: Partial<ComponentProps<typeof ResultsPage>> = {}) {
  return {
    origin: places[0],
    destinationName: places[1].name,
    visible: [] as Route[],
    selectedId: null,
    setSelectedId: vi.fn(),
    status: 'success' as const,
    retry: vi.fn(),
    error: '',
    enabled: ['walk', 'subway', 'bus', 'bike'] as Mode[],
    priority: 'fast' as const,
    setPriority: vi.fn(),
    openFilter: vi.fn(),
    openSearch: vi.fn(),
    onBackToInput: vi.fn(),
    go: vi.fn(),
    canSwap: true,
    swapPlaces: vi.fn(),
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  requests.prediction = null
  requests.stocks.length = 0
})

describe('결과 페이지 자전거 확인 표시', () => {
  it('재고·예측 확인 중에는 카드를 숨기고 완료 후 빠른 자전거를 한 번 추천한다', async () => {
    const bikeRoute: Route = {
      id: 'fast-bike',
      label: '빠른 자전거',
      minutes: 10,
      transfers: 0,
      modes: ['bike'],
      departedAt: '2026-09-27T08:00:00.000Z',
      legs: [
        {
          mode: 'bike',
          title: '대여소에서 반납소까지',
          note: '자전거',
          minutes: 10,
          from: { name: '대여소', rentalId: 'rental-start' },
          to: { name: '반납소', rentalId: 'rental-end' },
        },
      ],
    }
    const subwayRoute: Route = {
      id: 'slow-subway',
      label: '느린 지하철',
      minutes: 20,
      transfers: 0,
      modes: ['subway'],
      departedAt: '2026-09-27T08:00:00.000Z',
      legs: [{ mode: 'subway', title: '역에서 역까지', note: '2호선', minutes: 20 }],
    }
    const visible = [bikeRoute, subwayRoute]

    render(<ResultsPage {...props({ visible })} />)

    expect(screen.queryByRole('button', { name: /빠른 자전거/ })).toBeNull()
    expect(screen.queryByText('경로를 찾고 있어요')).not.toBeNull()
    expect(requests.prediction).not.toBeNull()
    expect(requests.stocks.map(({ rentalId }) => rentalId)).toEqual(['rental-start', 'rental-end'])

    await act(async () => {
      requests.prediction!.resolve({
        status: 'AVAILABLE',
        predictedBikes: 4,
        availabilityProbability: 0.9,
        predictedAt: '2026-09-27T07:55:00.000Z',
        arrivalTime: '2026-09-27T08:00:00.000Z',
        rentalId: 'rental-start',
        source: 'MOCK',
      })
      requests.stocks[0].deferred.resolve({
        rentalId: 'rental-start',
        availableBikes: 2,
        stockUpdatedAt: '2026-09-27T07:55:00.000Z',
        status: 'AVAILABLE',
        rackCount: 10,
      })
      requests.stocks[1].deferred.resolve({
        rentalId: 'rental-end',
        availableBikes: 1,
        stockUpdatedAt: '2026-09-27T07:55:00.000Z',
        status: 'AVAILABLE',
        rackCount: 10,
      })
      await Promise.resolve()
      await Promise.resolve()
    })

    await waitFor(() => {
      const bikeCard = screen.getByRole('button', { name: /빠른 자전거/ })
      expect(bikeCard).toBeTruthy()
      expect(screen.getByRole('region', { name: '추천 경로' }).contains(bikeCard)).toBe(true)
    })
    expect(screen.queryByText('경로를 찾고 있어요')).toBeNull()
  })
})
