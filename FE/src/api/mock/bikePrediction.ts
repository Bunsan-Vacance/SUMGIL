import { mapBikePrediction, type BikePredictionRepository } from '../bikePrediction'

export const bikePredictionMockResponse = {
  success: true,
  data: {
    status: 'AVAILABLE',
    predictedBikes: 6,
    availabilityProbability: 0.82,
    predictedAt: '2026-09-17T08:30:00+09:00',
    arrivalTime: '2026-09-17T08:38:00+09:00',
    rentalId: 'ST-1',
    source: 'MOCK',
  },
} as const

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timer = setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })
}

export const bikePredictionMockRepository: BikePredictionRepository = {
  async prediction(rentalId, arrivalTime, signal) {
    await delay(120, signal)
    const response = {
      ...bikePredictionMockResponse.data,
      rentalId,
      arrivalTime,
    }
    return mapBikePrediction(response)
  },
}
