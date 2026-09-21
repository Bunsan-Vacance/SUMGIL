// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
    expect(screen.getByText('따릉이 대여 예측')).toBeTruthy()
    expect(screen.getByText('강남 대여소 · 08:33 도착')).toBeTruthy()
    expect(screen.getByText('샘플')).toBeTruthy()
    expect(screen.queryByText(/현재 재고가 아니라/)).toBeNull()
    expect(screen.queryByText(/대여 가능성/)).toBeNull()
    expect(screen.queryByText(/모델 산출|산출/)).toBeNull()
  })

  it('명시적인 rentalId가 없으면 API를 호출하지 않는다', () => {
    const repository: BikePredictionRepository = { prediction: vi.fn() }
    const routeWithoutId = {
      ...route,
      legs: route.legs.map((leg) =>
        leg.mode === 'bike' ? { ...leg, from: { name: '대여소' } } : leg,
      ),
    }
    render(<BikePrediction route={routeWithoutId} repository={repository} />)
    expect(screen.getByText('이 대여소의 도착 시 예측 정보가 아직 없어요.')).toBeTruthy()
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
    const nextRoute = {
      ...route,
      id: 'next-route',
      legs: route.legs.map((leg) =>
        leg.mode === 'bike' ? { ...leg, from: { name: '새 대여소', rentalId: 'ST-9' } } : leg,
      ),
    }
    rerender(<BikePrediction route={nextRoute} repository={repository} />)
    expect(vi.mocked(repository.prediction).mock.calls[0][2].aborted).toBe(true)
    await act(async () => resolveSecond(nextPrediction))
    await waitFor(() => expect(screen.getByText('4대 예상')).toBeTruthy())
    await act(async () => resolveFirst(prediction))
    expect(screen.getByText('4대 예상')).toBeTruthy()
  })
})
