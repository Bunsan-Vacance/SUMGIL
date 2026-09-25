import type { BikeStationRepository, BikeStock } from '../contracts'

export const bikeStockMockResponse: BikeStock = {
  rentalId: 'ST-1',
  availableBikes: 6,
  rackCount: 6,
  stockUpdatedAt: new Date().toISOString(),
  status: 'AVAILABLE',
}

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

export const bikeStockMockRepository: BikeStationRepository = {
  async nearby(_request, signal) {
    await delay(0, signal)
    return []
  },
  async stock(rentalId, signal) {
    await delay(120, signal)
    return {
      ...bikeStockMockResponse,
      rentalId,
      availableBikes: 6,
      rackCount: 6,
      stockUpdatedAt: new Date().toISOString(),
    }
  },
}
