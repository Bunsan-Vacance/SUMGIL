import type { PlaceRepository, RouteRepository } from '../contracts'
import { mapRouteApiResponse } from '../routeMapper'
import { places, routes } from './fixtures'
import { routeSearchMockResponse } from './routeResponses'

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
  async search(request, signal) {
    // Preview-only: arbitrary endpoints do not change the fixed sample route.
    await delay(450, signal)
    return routes.map((route) => ({
      ...route,
      departedAt: request.departedAt || route.departedAt || new Date().toISOString(),
    }))
  },
}
export const routeSearchMockRepository: RouteRepository = {
  async search(request, signal) {
    await delay(450, signal)
    return mapRouteApiResponse(
      routeSearchMockResponse,
      request.departedAt || new Date().toISOString(),
    )
  },
}
export const mockPlaceRepository: PlaceRepository = {
  async search(query, signal) {
    await delay(100, signal)
    return places.filter((place) => `${place.name} ${place.address}`.includes(query.trim()))
  },
}
