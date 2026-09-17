import { requestApi } from './repositories'
import { RepositoryError } from './errors'

export type BikePredictionStatus = 'AVAILABLE' | 'UNAVAILABLE'
export type BikePredictionSource = 'MODEL' | 'MOCK'

export interface BikePrediction {
  status: BikePredictionStatus
  predictedBikes: number | null
  availabilityProbability: number | null
  predictedAt: string | null
  arrivalTime: string
  rentalId: string
  source: BikePredictionSource
}

export interface BikePredictionRepository {
  prediction(rentalId: string, arrivalTime: string, signal: AbortSignal): Promise<BikePrediction>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function text(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function iso(value: unknown) {
  const timestamp = text(value)
  return timestamp &&
    /(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp) &&
    Number.isFinite(new Date(timestamp).getTime())
    ? timestamp
    : undefined
}

export function mapBikePrediction(value: unknown): BikePrediction {
  if (!isRecord(value) || !text(value.rentalId)) {
    throw new RepositoryError('invalid-response', '따릉이 도착 예측 응답이 올바르지 않아요.')
  }
  if (value.status !== 'AVAILABLE' && value.status !== 'UNAVAILABLE') {
    throw new RepositoryError('invalid-response', '따릉이 도착 예측 상태가 올바르지 않아요.')
  }
  const predictedBikes = value.predictedBikes
  if (
    predictedBikes !== null &&
    (!Number.isSafeInteger(predictedBikes) || (predictedBikes as number) < 0)
  ) {
    throw new RepositoryError('invalid-response', '따릉이 도착 예측 수량이 올바르지 않아요.')
  }
  const probability = value.availabilityProbability
  if (
    probability !== undefined &&
    probability !== null &&
    (typeof probability !== 'number' ||
      !Number.isFinite(probability) ||
      probability < 0 ||
      probability > 1)
  ) {
    throw new RepositoryError('invalid-response', '따릉이 도착 예측 확률이 올바르지 않아요.')
  }
  if (value.status === 'AVAILABLE' && (predictedBikes === null || !iso(value.predictedAt))) {
    throw new RepositoryError('invalid-response', '예측 가능 응답에 예측 값이 없어요.')
  }
  if (
    value.status === 'UNAVAILABLE' &&
    (predictedBikes !== null ||
      (probability !== undefined && probability !== null) ||
      value.predictedAt !== null)
  ) {
    throw new RepositoryError('invalid-response', '예측 불가 응답에 수량이 포함되어 있어요.')
  }
  const predictedAt = value.predictedAt === null ? null : (iso(value.predictedAt) ?? null)
  const arrivalTime = iso(value.arrivalTime)
  if (value.status === 'AVAILABLE' && !predictedAt) {
    throw new RepositoryError('invalid-response', '예측 산출 시각이 올바르지 않아요.')
  }
  if (!arrivalTime) {
    throw new RepositoryError('invalid-response', '따릉이 도착 예측 시각이 올바르지 않아요.')
  }
  if (value.source !== 'MODEL' && value.source !== 'MOCK') {
    throw new RepositoryError('invalid-response', '따릉이 도착 예측 출처가 올바르지 않아요.')
  }
  return {
    status: value.status,
    predictedBikes: predictedBikes as number | null,
    availabilityProbability: (probability as number | null | undefined) ?? null,
    predictedAt,
    arrivalTime,
    rentalId: text(value.rentalId) as string,
    source: value.source,
  }
}

export function createBackendBikePredictionRepository(baseUrl: string): BikePredictionRepository {
  return {
    async prediction(rentalId, arrivalTime, signal) {
      const id = rentalId.trim()
      if (!id || !iso(arrivalTime)) {
        throw new RepositoryError('bad-request', '대여소와 도착 시각을 확인해 주세요.')
      }
      const params = new URLSearchParams({ arrivalTime })
      try {
        const data = await requestApi<unknown>(
          `${baseUrl}/api/bike-stations/${encodeURIComponent(id)}/prediction?${params}`,
          signal,
        )
        const prediction = mapBikePrediction(data)
        if (
          prediction.rentalId !== id ||
          new Date(prediction.arrivalTime).getTime() !== new Date(arrivalTime).getTime()
        ) {
          throw new RepositoryError('invalid-response', '따릉이 도착 예측 대상이 요청과 달라요.')
        }
        return prediction
      } catch (error) {
        if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
        if (error instanceof RepositoryError && error.status === 404) {
          throw new RepositoryError('bike-station-not-found', '따릉이 대여소를 찾지 못했어요.', 404)
        }
        throw error
      }
    },
  }
}
