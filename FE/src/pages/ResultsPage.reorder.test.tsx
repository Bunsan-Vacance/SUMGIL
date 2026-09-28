// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import type { BikePrediction } from '../api/bikePrediction'
import type { BikeStock } from '../api/contracts'
import type { Mode, Route } from '../features/route/types'
import { places } from '../api/mock/fixtures'
import ResultsPage from './ResultsPage'

const requests = vi.hoisted(() => ({
  prediction: 0,
  stocks: [] as string[],
}))

vi.mock('../api/repositories', () => ({
  bikePredictionRepository: {
    prediction: vi.fn(() => {
      requests.prediction += 1
      return Promise.resolve({} as BikePrediction)
    }),
  },
  bikeStockRepository: {
    stock: vi.fn((rentalId: string) => {
      requests.stocks.push(rentalId)
      return Promise.resolve({
        rentalId,
        availableBikes: 2,
        stockUpdatedAt: '2026-09-27T07:55:00.000Z',
        status: 'AVAILABLE',
        rackCount: 2,
      } satisfies BikeStock)
    }),
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
  requests.prediction = 0
  requests.stocks.length = 0
})

describe('결과 페이지 추천 경로 표시', () => {
  it('재고·예측 요청을 기다리지 않고 자전거 경로를 즉시 추천한다', () => {
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

    render(<ResultsPage {...props({ visible: [bikeRoute, subwayRoute] })} />)

    const bikeCard = screen.getByRole('button', { name: /빠른 자전거/ })
    expect(screen.getByRole('region', { name: '추천 경로' }).contains(bikeCard)).toBe(true)
    expect(screen.queryByText('경로를 찾고 있어요')).toBeNull()
    expect(requests.prediction).toBe(0)
    expect(requests.stocks).toEqual([])
  })
})
