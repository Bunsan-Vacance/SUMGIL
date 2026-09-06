import type { PlaceRepository, RouteRepository } from '../contracts'
import { places, routes } from './fixtures'

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const abort = () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, ms)
    signal.addEventListener('abort', abort, { once: true })
  })
}
export const mockRouteRepository: RouteRepository = {
  async search(_request, signal) {
    // Preview-only: arbitrary endpoints do not change the fixed sample route.
    await delay(450, signal)
    return routes
  },
}
export const mockPlaceRepository: PlaceRepository = {
  async search(query, signal) {
    await delay(100, signal)
    return places.filter((place) => `${place.name} ${place.address}`.includes(query.trim()))
  },
}
