import rawBikeStations from '../../data/bike-stations.json'
import type { Place } from '../route/types'

export interface BikeStation {
  id: string
  name: string
  address: string
  lat: number
  lng: number
  dockCount?: number
  distanceMeters?: number
  availableBikes?: number | null
  stockUpdatedAt?: string | null
}

export interface NearbyBikeStationLike {
  id: string
  name: string
  address?: string
  lat: number
  lng: number
  dockCount?: number
  distanceMeters?: number
  availableBikes?: number | null
  stockUpdatedAt?: string | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isCoordinate(value: unknown, min: number, max: number) {
  return (
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value !== 0 &&
    value >= min &&
    value <= max
  )
}

export function parseBikeStations(value: unknown): BikeStation[] {
  if (!Array.isArray(value)) throw new Error('invalid-bike-station-data')
  const ids = new Set<string>()
  const stations = value.map((item) => {
    if (
      !isRecord(item) ||
      typeof item.id !== 'string' ||
      !item.id.trim() ||
      typeof item.name !== 'string' ||
      !item.name.trim() ||
      typeof item.address !== 'string' ||
      !item.address.trim() ||
      !isCoordinate(item.lat, -90, 90) ||
      !isCoordinate(item.lng, -180, 180)
    ) {
      throw new Error('invalid-bike-station-data')
    }
    const station = {
      id: item.id.trim(),
      name: item.name.trim(),
      address: item.address.trim(),
      lat: item.lat as number,
      lng: item.lng as number,
    }
    if (ids.has(station.id)) throw new Error('duplicate-bike-station-id')
    ids.add(station.id)
    return station
  })
  return stations
}

export const bikeStations = parseBikeStations(rawBikeStations)

export function getBikeStationDisplayName(name: string) {
  return /^따릉이 대여소\s+ST-[\w-]+$/i.test(name.trim()) ? '따릉이 대여소' : name.trim()
}

export function stationToPlace(station: BikeStation): Place {
  return {
    id: `bike-station:${station.id}`,
    name: getBikeStationDisplayName(station.name),
    address: station.address,
    kind: '따릉이 대여소',
    lat: station.lat,
    lng: station.lng,
    ...(station.dockCount !== undefined ? { dockCount: station.dockCount } : {}),
    ...(station.distanceMeters !== undefined ? { distanceMeters: station.distanceMeters } : {}),
  }
}

export function nearbyStationToBikeStation(station: NearbyBikeStationLike): BikeStation {
  return {
    id: station.id,
    name: station.name,
    address: station.address?.trim() || '',
    lat: station.lat,
    lng: station.lng,
    ...(station.dockCount !== undefined ? { dockCount: station.dockCount } : {}),
    ...(station.distanceMeters !== undefined ? { distanceMeters: station.distanceMeters } : {}),
    ...(station.availableBikes !== undefined ? { availableBikes: station.availableBikes } : {}),
    ...(station.stockUpdatedAt !== undefined ? { stockUpdatedAt: station.stockUpdatedAt } : {}),
  }
}

export function bikeRentalId(place: Place) {
  if (place.rentalId) return place.rentalId
  if (place.id.startsWith('bike-station:')) return place.id.slice('bike-station:'.length)
  return undefined
}
