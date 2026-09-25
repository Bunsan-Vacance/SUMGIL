// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BikeStationRepository, BikeStock } from '../../api/contracts'
import type { BikePredictionRepository } from '../../api/bikePrediction'
import type { Route } from './types'
import BikePrediction from './BikePrediction'

afterEach(cleanup)

const route: Route = {
  id: 'bike-route',
  label: '따릉이 경로',
  minutes: 14,
  transfers: 0,
  modes: ['walk', 'bike'],
  departedAt: '2026-09-17T08:30:00+09:00',
  legs: [
    { mode: 'walk', title: '대여소까지 이동', note: '', minutes: 3 },
    {
      mode: 'bike',
      title: '따릉이 이용',
      note: '',
      minutes: 8,
      from: { name: '강남 대여소', rentalId: 'ST-1' },
      to: { name: '역삼 대여소', rentalId: 'ST-2' },
    },
  ],
}

const prediction = {
  status: 'AVAILABLE' as const,
  predictedBikes: 4,
  availabilityProbability: 0.75,
  predictedAt: '2026-09-17T08:31:00+09:00',
  arrivalTime: '2026-09-16T23:33:00.000Z',
  rentalId: 'ST-1',
  source: 'MOCK' as const,
}
const unavailablePrediction = {
  ...prediction,
  status: 'UNAVAILABLE' as const,
  predictedBikes: null,
  predictedAt: null,
}
const stock: BikeStock = {
  rentalId: 'ST-1',
  availableBikes: 6,
  stockUpdatedAt: '2026-09-17T08:31:00+09:00',
  status: 'AVAILABLE',
}

describe('BikePrediction', () => {
  it('첫 BIKE 구간 이전 minutes 합으로 대여소 도착 시각을 요청한다', async () => {
    const repository: BikePredictionRepository = {
      prediction: vi.fn().mockResolvedValue(prediction),
    }
    render(<BikePrediction route={route} repository={repository} />)
    await waitFor(() => expect(screen.getByText('4대 예상')).toBeTruthy())
    expect(repository.prediction).toHaveBeenCalledWith(
      'ST-1',
      '2026-09-16T23:33:00.000Z',
      expect.any(AbortSignal),
    )
    expect(screen.getByText('따릉이 대여 정보')).toBeTruthy()
    expect(screen.getByText('강남 대여소')).toBeTruthy()
    expect(screen.queryByText('샘플')).toBeNull()
    expect(screen.queryByText(/현재 재고가 아니라/)).toBeNull()
    expect(screen.queryByText(/대여 가능성/)).toBeNull()
    expect(screen.queryByText(/모델 산출|산출/)).toBeNull()
  })

  it('현재 재고와 도착 시 예측을 같은 카드에 함께 표시한다', async () => {
    const repository: BikePredictionRepository = {
      prediction: vi.fn().mockResolvedValue(prediction),
    }
    const stockRepository: Pick<BikeStationRepository, 'stock'> = {
      stock: vi.fn().mockResolvedValue(stock),
    }
    render(
      <BikePrediction route={route} repository={repository} stockRepository={stockRepository} />,
    )
    await waitFor(() => expect(screen.getByText('6대')).toBeTruthy())
    expect(screen.getByText('현재')).toBeTruthy()
    expect(screen.getByText('08:33')).toBeTruthy()
    expect(screen.getByText('4대 예상')).toBeTruthy()
    expect(stockRepository.stock).toHaveBeenCalledWith('ST-1', expect.any(AbortSignal))
  })

  it('현재 재고와 예측 수량이 0대여도 0을 표시한다', async () => {
    const repository: BikePredictionRepository = {
      prediction: vi.fn().mockResolvedValue({ ...prediction, predictedBikes: 0 }),
    }
    const stockRepository: Pick<BikeStationRepository, 'stock'> = {
      stock: vi.fn().mockResolvedValue({ ...stock, availableBikes: 0 }),
    }
    render(
      <BikePrediction route={route} repository={repository} stockRepository={stockRepository} />,
    )
    await waitFor(() => expect(screen.getByText('0대 예상')).toBeTruthy())
    expect(screen.getByText('0대')).toBeTruthy()
    expect(screen.getByText('도착 시 대여할 자전거가 없어요.')).toBeTruthy()
  })

  it('오래된 재고는 현재가 아닌 마지막 확인 시각으로 표시한다', async () => {
    const repository: BikePredictionRepository = {
      prediction: vi.fn().mockResolvedValue(prediction),
    }
    const stockRepository: Pick<BikeStationRepository, 'stock'> = {
      stock: vi.fn().mockResolvedValue({ ...stock, availableBikes: 2, status: 'STALE' }),
    }
    render(
      <BikePrediction route={route} repository={repository} stockRepository={stockRepository} />,
    )
    await waitFor(() => expect(screen.getByText('마지막 확인 08:31')).toBeTruthy())
    expect(screen.getByText('2대')).toBeTruthy()
    expect(screen.queryByText('현재')).toBeNull()
  })

  it('재고 UNAVAILABLE과 API 오류를 별도로 안내하고 오류는 재시도한다', async () => {
    const repository: BikePredictionRepository = {
      prediction: vi.fn().mockResolvedValue(prediction),
    }
    let sourceCalls = 0
    const stockRepository: Pick<BikeStationRepository, 'stock'> = {
      stock: vi.fn((rentalId) => {
        if (rentalId === 'ST-2') {
          return Promise.resolve({ ...stock, rentalId: 'ST-2', availableBikes: 6, rackCount: 6 })
        }
        sourceCalls += 1
        if (sourceCalls === 1) {
          return Promise.resolve({
            ...stock,
            availableBikes: null,
            stockUpdatedAt: null,
            status: 'UNAVAILABLE' as const,
          })
        }
        if (sourceCalls === 2) return Promise.reject(new Error('offline'))
        return Promise.resolve(stock)
      }),
    }
    const { rerender } = render(
      <BikePrediction route={route} repository={repository} stockRepository={stockRepository} />,
    )
    await waitFor(() => expect(screen.getByText('재고 정보 없음')).toBeTruthy())
    await waitFor(() => expect(screen.getByText(/반납 대여소가 혼잡해요/)).toBeTruthy())
    rerender(
      <BikePrediction
        route={{ ...route, id: 'retry-stock' }}
        repository={repository}
        stockRepository={stockRepository}
      />,
    )
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByText('현재 재고를 불러오지 못했어요.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '재고 다시 시도' }))
    await waitFor(() => expect(screen.getByText('6대')).toBeTruthy())
  })

  it('명시적인 rentalId가 없으면 API를 호출하지 않는다', async () => {
    const repository: BikePredictionRepository = { prediction: vi.fn() }
    const routeWithoutId = {
      ...route,
      legs: route.legs.map((leg) =>
        leg.mode === 'bike' ? { ...leg, from: { name: '대여소' } } : leg,
      ),
    }
    render(<BikePrediction route={routeWithoutId} repository={repository} />)
    await waitFor(() =>
      expect(screen.getByText('이 대여소의 도착 시 예측 정보가 아직 없어요.')).toBeTruthy(),
    )
    expect(repository.prediction).not.toHaveBeenCalled()
  })

  it('오류 뒤 다시 시도하면 새 요청을 보내고 늦은 응답은 반영하지 않는다', async () => {
    const repository: BikePredictionRepository = {
      prediction: vi
        .fn()
        .mockRejectedValueOnce(new Error('offline'))
        .mockResolvedValueOnce(prediction),
    }
    render(<BikePrediction route={route} repository={repository} />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    await waitFor(() => expect(screen.getByText('4대 예상')).toBeTruthy())
    expect(repository.prediction).toHaveBeenCalledTimes(2)
  })

  it('예측 불가 응답은 정보 없음 문구 하나로 표시한다', async () => {
    const repository: BikePredictionRepository = {
      prediction: vi.fn().mockResolvedValue(unavailablePrediction),
    }
    render(<BikePrediction route={route} repository={repository} />)
    await waitFor(() => expect(screen.getByText('도착 시 예측 정보 없음')).toBeTruthy())
    expect(screen.queryByText('예측 수량 없음')).toBeNull()
    expect(screen.queryByText('도착 시 예측을 제공할 수 없어요.')).toBeNull()
  })

  it('경로가 바뀌면 이전 요청을 취소한다', async () => {
    let resolveFirst!: (value: typeof prediction) => void
    let resolveSecond!: (value: typeof prediction) => void
    const nextPrediction = { ...prediction, rentalId: 'ST-9' }
    const repository: BikePredictionRepository = {
      prediction: vi
        .fn()
        .mockImplementationOnce(() => new Promise((yes) => (resolveFirst = yes)))
        .mockImplementationOnce(() => new Promise((yes) => (resolveSecond = yes))),
    }
    const { rerender } = render(<BikePrediction route={route} repository={repository} />)
    await waitFor(() => expect(repository.prediction).toHaveBeenCalledTimes(1))
    const nextRoute = {
      ...route,
      id: 'next-route',
      legs: route.legs.map((leg) =>
        leg.mode === 'bike' ? { ...leg, from: { name: '새 대여소', rentalId: 'ST-9' } } : leg,
      ),
    }
    rerender(<BikePrediction route={nextRoute} repository={repository} />)
    await waitFor(() => expect(repository.prediction).toHaveBeenCalledTimes(2))
    expect(vi.mocked(repository.prediction).mock.calls[0][2].aborted).toBe(true)
    await act(async () => resolveSecond(nextPrediction))
    await waitFor(() => expect(screen.getByText('4대 예상')).toBeTruthy())
    await act(async () => resolveFirst(prediction))
    expect(screen.getByText('4대 예상')).toBeTruthy()
  })

  it('경로가 바뀐 뒤 이전 재고 응답을 표시하지 않는다', async () => {
    let resolveFirst!: (value: BikeStock) => void
    let resolveSecond!: (value: BikeStock) => void
    const stockRepository: Pick<BikeStationRepository, 'stock'> = {
      stock: vi.fn((rentalId: string, _signal: AbortSignal): Promise<BikeStock> => {
        if (rentalId === 'ST-1') return new Promise((yes) => (resolveFirst = yes))
        if (rentalId === 'ST-9') return new Promise((yes) => (resolveSecond = yes))
        return Promise.resolve({ ...stock, rentalId, availableBikes: 6, rackCount: 6 })
      }),
    }
    const { rerender } = render(
      <BikePrediction route={route} repository={null} stockRepository={stockRepository} />,
    )
    await waitFor(() =>
      expect(stockRepository.stock).toHaveBeenCalledWith('ST-1', expect.any(AbortSignal)),
    )
    const nextRoute = {
      ...route,
      id: 'next-stock-route',
      legs: route.legs.map((leg) =>
        leg.mode === 'bike' ? { ...leg, from: { name: '새 대여소', rentalId: 'ST-9' } } : leg,
      ),
    }
    rerender(
      <BikePrediction route={nextRoute} repository={null} stockRepository={stockRepository} />,
    )
    await waitFor(() =>
      expect(stockRepository.stock).toHaveBeenCalledWith('ST-9', expect.any(AbortSignal)),
    )
    await act(async () => resolveSecond({ ...stock, rentalId: 'ST-9', availableBikes: 9 }))
    await waitFor(() => expect(screen.getByText('9대')).toBeTruthy())
    await act(async () => resolveFirst({ ...stock, availableBikes: 1 }))
    expect(screen.queryByText('1대')).toBeNull()
    expect(screen.getByText('9대')).toBeTruthy()
  })
})
