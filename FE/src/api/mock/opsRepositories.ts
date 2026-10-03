import type { OpsRepository } from '../contracts'
import { buildBikeStockSample, buildHeatmapSample } from './opsFixtures'

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const onAbort = () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

// VITE_OPS_MOCK=true일 때만 선택된다. 결과의 source는 항상 'mock'이다.
export const opsMockRepository: OpsRepository = {
  async bikeStockOverview(request, signal) {
    await delay(300, signal)
    return { source: 'mock', data: buildBikeStockSample(request) }
  },
  async congestionHeatmap(request, signal) {
    await delay(300, signal)
    return { source: 'mock', data: buildHeatmapSample(request.date) }
  },
}
