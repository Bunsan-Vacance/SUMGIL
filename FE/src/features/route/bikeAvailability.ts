import { useEffect, useMemo, useState } from 'react'
import { bikePredictionRepository, bikeStockRepository } from '../../api/repositories'
import type { BikePredictionRepository } from '../../api/bikePrediction'
import type { BikeStationRepository, BikeStock } from '../../api/contracts'
import type { Leg, Route } from './types'

export interface PredictionTarget {
  leg: Leg
  rentalId: string
  arrivalTime: string
}

export type BikeRouteAvailabilityStatus =
  | 'checking'
  | 'available'
  | 'rental-unavailable'
  | 'rental-unavailable-current'
  | 'return-crowded'
  | 'unknown'

export function bikeRouteAvailabilityMessage(status: BikeRouteAvailabilityStatus) {
  if (status === 'rental-unavailable') {
    return '도착 시 대여할 자전거가 없어요. 다른 경로를 선택해 주세요.'
  }
  if (status === 'rental-unavailable-current') {
    return '현재 대여 가능한 자전거가 없어요. 도착 시 이용 가능 여부는 확인이 필요해요.'
  }
  if (status === 'return-crowded') {
    return '반납 대여소가 혼잡해요. 현장 반납 공간을 확인해 주세요.'
  }
  if (status === 'checking') return '따릉이 재고를 확인하고 있어요.'
  if (status === 'unknown') return '따릉이 이용 가능 여부를 확인할 수 없어요.'
  return null
}

export interface BikeRouteAvailability {
  status: BikeRouteAvailabilityStatus
  stockUpdatedAt: string | null
  stockBasis: 'rental' | 'return' | null
}

export interface BikeAvailabilityRepositories {
  prediction?: BikePredictionRepository | null
  stock?: Pick<BikeStationRepository, 'stock'> | null
}

const BIKE_AVAILABILITY_TIMEOUT_MS = 10_000

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

function returnTarget(route: Route): { leg: Leg; rentalId: string } | null {
  const leg = route.legs.find((candidate) => candidate.mode === 'bike')
  const rentalId = leg?.to?.rentalId?.trim()
  return leg && rentalId ? { leg, rentalId } : null
}

export function bikePredictionTargetForRoute(route: Route) {
  return predictionTarget(route)
}

export function bikeStockTargetForRoute(route: Route) {
  return stockTarget(route)
}

export function bikeReturnTargetForRoute(route: Route) {
  return returnTarget(route)
}

function usableStock(
  stock: BikeStock | null,
): stock is BikeStock & { status: 'AVAILABLE'; availableBikes: number } {
  return stock?.status === 'AVAILABLE' && stock.availableBikes !== null
}

export async function loadBikeRouteAvailability(
  route: Route,
  signal: AbortSignal,
  repositories: BikeAvailabilityRepositories = {
    prediction: bikePredictionRepository,
    stock: bikeStockRepository,
  },
): Promise<BikeRouteAvailability> {
  const target = predictionTarget(route)
  const stockTargetForRoute = stockTarget(route)
  const returnTargetForRoute = returnTarget(route)
  const predictionRequest =
    target && repositories.prediction
      ? repositories.prediction.prediction(target.rentalId, target.arrivalTime, signal)
      : null
  const stockRequest =
    stockTargetForRoute && repositories.stock
      ? repositories.stock.stock(stockTargetForRoute.rentalId, signal)
      : null
  const returnStockRequest =
    returnTargetForRoute &&
    repositories.stock &&
    returnTargetForRoute.rentalId !== stockTargetForRoute?.rentalId
      ? repositories.stock.stock(returnTargetForRoute.rentalId, signal)
      : null
  const [predictionResult, stockResult, returnStockResult] = await Promise.all([
    predictionRequest
      ? predictionRequest
          .then((value) => ({ ok: true as const, value }))
          .catch(() => ({ ok: false as const }))
      : Promise.resolve({ ok: false as const }),
    stockRequest
      ? stockRequest
          .then((value) => ({ ok: true as const, value }))
          .catch(() => ({ ok: false as const }))
      : Promise.resolve({ ok: false as const }),
    returnStockRequest
      ? returnStockRequest
          .then((value) => ({ ok: true as const, value }))
          .catch(() => ({ ok: false as const }))
      : Promise.resolve({ ok: false as const }),
  ])
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError')

  const prediction = predictionResult.ok ? predictionResult.value : null
  const stock = stockResult.ok ? stockResult.value : null
  const returnStock = returnStockResult.ok
    ? returnStockResult.value
    : returnTargetForRoute?.rentalId === stockTargetForRoute?.rentalId
      ? stock
      : null
  const predictionAvailable =
    prediction?.status === 'AVAILABLE' && prediction.predictedBikes !== null
  if (predictionAvailable && prediction?.predictedBikes === 0) {
    return {
      status: 'rental-unavailable',
      stockUpdatedAt: stock?.stockUpdatedAt ?? null,
      stockBasis: 'rental',
    }
  }
  if (!predictionAvailable && usableStock(stock) && stock.availableBikes === 0) {
    return {
      status: 'rental-unavailable-current',
      stockUpdatedAt: stock.stockUpdatedAt,
      stockBasis: 'rental',
    }
  }
  const returnStockIsCrowded =
    usableStock(returnStock) &&
    returnStock.rackCount !== undefined &&
    returnStock.rackCount !== null &&
    returnStock.rackCount > 0 &&
    returnStock.availableBikes >= returnStock.rackCount
  if (returnStockIsCrowded) {
    return {
      status: 'return-crowded',
      stockUpdatedAt: returnStock.stockUpdatedAt,
      stockBasis: 'return',
    }
  }
  const returnAvailabilityKnown =
    usableStock(returnStock) &&
    returnStock.rackCount !== undefined &&
    returnStock.rackCount !== null &&
    returnStock.rackCount > 0 &&
    returnStock.availableBikes < returnStock.rackCount
  if (predictionAvailable && returnAvailabilityKnown) {
    return {
      status: 'available',
      stockUpdatedAt: stock?.stockUpdatedAt ?? null,
      stockBasis: 'rental',
    }
  }
  return {
    status: 'unknown',
    stockUpdatedAt: returnTargetForRoute
      ? (returnStock?.stockUpdatedAt ?? null)
      : (stock?.stockUpdatedAt ?? null),
    stockBasis: returnTargetForRoute ? 'return' : stock ? 'rental' : null,
  }
}

export function useBikeRouteAvailability(
  routes: Route[],
  repositories?: BikeAvailabilityRepositories,
) {
  const bikeRoutes = useMemo(
    () => routes.filter((route) => route.legs.some((leg) => leg.mode === 'bike')),
    [routes],
  )
  const batch = useMemo(() => ({ bikeRoutes, repositories }), [bikeRoutes, repositories])
  const initialAvailability = useMemo(
    () =>
      Object.fromEntries(
        bikeRoutes.map((route) => [
          route.id,
          { status: 'checking' as const, stockUpdatedAt: null, stockBasis: null },
        ]),
      ),
    [bikeRoutes],
  )
  const [completedBatch, setCompletedBatch] = useState<{
    batch: typeof batch
    availability: Record<string, BikeRouteAvailability>
  } | null>(null)
  useEffect(() => {
    if (!batch.bikeRoutes.length) return
    const controller = new AbortController()
    let active = true
    const settled = new Map<string, BikeRouteAvailability>()
    let timeoutId: ReturnType<typeof setTimeout> | undefined

    const publish = () => {
      if (!active) return
      setCompletedBatch({ batch, availability: Object.fromEntries(settled) })
    }
    const settle = (routeId: string, value: BikeRouteAvailability) => {
      if (!active || settled.has(routeId)) return
      settled.set(routeId, value)
      if (settled.size === batch.bikeRoutes.length) {
        publish()
        active = false
        if (timeoutId !== undefined) clearTimeout(timeoutId)
      }
    }

    timeoutId = setTimeout(() => {
      if (!active) return
      controller.abort()
      for (const route of batch.bikeRoutes) {
        if (!settled.has(route.id))
          settled.set(route.id, {
            status: 'unknown',
            stockUpdatedAt: null,
            stockBasis: null,
          })
      }
      publish()
      active = false
    }, BIKE_AVAILABILITY_TIMEOUT_MS)

    batch.bikeRoutes.forEach((route) => {
      loadBikeRouteAvailability(route, controller.signal, batch.repositories)
        .then((value) => settle(route.id, value))
        .catch(() =>
          settle(route.id, { status: 'unknown', stockUpdatedAt: null, stockBasis: null }),
        )
    })
    return () => {
      active = false
      controller.abort()
      if (timeoutId !== undefined) clearTimeout(timeoutId)
    }
  }, [batch])
  return completedBatch?.batch === batch ? completedBatch.availability : initialAvailability
}
