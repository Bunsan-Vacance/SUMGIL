import type { Leg, Route } from './types'

export interface PredictionTarget {
  leg: Leg
  rentalId: string
  arrivalTime: string
}

function predictionTarget(route: Route): PredictionTarget | null {
  if (!route.departedAt || !Number.isFinite(new Date(route.departedAt).getTime())) return null
  let elapsedMinutes = 0
  for (const leg of route.legs) {
    if (leg.mode === 'bike') {
      const rentalId = leg.from?.rentalId?.trim()
      if (!rentalId) return null
      return {
        leg,
        rentalId,
        arrivalTime: new Date(
          new Date(route.departedAt).getTime() + elapsedMinutes * 60_000,
        ).toISOString(),
      }
    }
    elapsedMinutes += leg.minutes
  }
  return null
}

function stockTarget(route: Route): { leg: Leg; rentalId: string } | null {
  const leg = route.legs.find((candidate) => candidate.mode === 'bike')
  const rentalId = leg?.from?.rentalId?.trim()
  return leg && rentalId ? { leg, rentalId } : null
}

export function bikePredictionTargetForRoute(route: Route) {
  return predictionTarget(route)
}

export function bikeStockTargetForRoute(route: Route) {
  return stockTarget(route)
}
