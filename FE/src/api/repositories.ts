import { mockPlaceRepository, mockRouteRepository } from './mock/repositories'

// Replace these adapters when the backend contract is agreed. UI imports only ports.
export const routeRepository = mockRouteRepository
export const placeRepository = mockPlaceRepository
