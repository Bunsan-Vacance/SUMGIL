import { afterEach, describe, expect, it, vi } from 'vitest'
import { RepositoryError } from './errors'
import { createBackendBikePredictionRepository, mapBikePrediction } from './bikePrediction'

const available = {
  status: 'AVAILABLE',
  predictedBikes: 0,
  availabilityProbability: null,
  predictedAt: '2026-09-17T08:30:00+09:00',
  arrivalTime: '2026-09-17T08:38:00+09:00',
  rentalId: 'ST-1',
  source: 'MODEL',
} as const

afterEach(() => vi.unstubAllGlobals())

describe('따릉이 도착 예측 계약', () => {
  it('0대는 유효한 예측값으로 보존한다', () => {
    expect(mapBikePrediction(available)).toMatchObject({
      status: 'AVAILABLE',
      predictedBikes: 0,
      availabilityProbability: null,
    })
  })

  it('예측 불가는 수량·확률·산출 시각을 null로 보존한다', () => {
    expect(
      mapBikePrediction({
        ...available,
        status: 'UNAVAILABLE',
        predictedBikes: null,
        predictedAt: null,
        source: 'MODEL',
      }),
    ).toMatchObject({
      status: 'UNAVAILABLE',
      predictedBikes: null,
      availabilityProbability: null,
      predictedAt: null,
    })
  })

  it('AVAILABLE의 수량 누락과 범위를 벗어난 확률을 거부한다', () => {
    expect(() => mapBikePrediction({ ...available, predictedBikes: null })).toThrow(RepositoryError)
    expect(() => mapBikePrediction({ ...available, availabilityProbability: 1.1 })).toThrow(
      RepositoryError,
    )
  })

  it('rentalId와 offset ISO 도착 시각을 query로 전달한다', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: available,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const repository = createBackendBikePredictionRepository('https://api.example.test')
    await repository.prediction('ST-1', available.arrivalTime, new AbortController().signal)
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.test/api/bike-stations/ST-1/prediction?arrivalTime=2026-09-17T08%3A38%3A00%2B09%3A00',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })
})
