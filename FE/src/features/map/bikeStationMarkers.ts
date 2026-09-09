import type { KakaoMapInstance, KakaoMaps } from '../../lib/kakao/sdk'
import { bikeStations, getBikeStationDisplayName, type BikeStation } from './bikeStations'

const BIKE_ICON =
  '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="5" cy="18" r="3"/><circle cx="19" cy="18" r="3"/><path d="M5 18 9 7h5l5 11M9 7l3 11m-5-6h8m-1-5h3"/></svg>'

export interface BikeStationOverlay {
  element: HTMLButtonElement
  setSelected(selected: boolean): void
  destroy(): void
}

export interface BikeStationGroup {
  stations: BikeStation[]
  center: { lat: number; lng: number }
}

export const BIKE_STATION_CLUSTER_LEVEL = 6
export const BIKE_STATION_CLUSTER_GRID_SIZE = 80

export function createBikeStationOverlay(
  maps: KakaoMaps,
  map: KakaoMapInstance,
  station: BikeStation,
  selected: boolean,
  onSelect: () => void,
): BikeStationOverlay {
  const element = document.createElement('button')
  element.type = 'button'
  element.className = 'bike-station-marker'
  const displayName = getBikeStationDisplayName(station.name)
  const markerLabel =
    displayName === '따릉이 대여소'
      ? `따릉이 대여소 · ${station.address}`
      : `${displayName} · 따릉이 대여소`
  element.setAttribute('aria-label', markerLabel)
  element.title = markerLabel
  element.innerHTML = BIKE_ICON
  const setSelected = (value: boolean) => {
    element.classList.toggle('selected', value)
    element.setAttribute('aria-pressed', String(value))
  }
  setSelected(selected)
  element.addEventListener('click', onSelect)
  const overlay = new maps.CustomOverlay({
    map,
    position: new maps.LatLng(station.lat, station.lng),
    content: element,
    clickable: true,
  })
  return {
    element,
    setSelected,
    destroy() {
      element.removeEventListener('click', onSelect)
      overlay.setMap(null)
    },
  }
}

export function visibleBikeStations(
  maps: KakaoMaps,
  map: KakaoMapInstance,
  stations: BikeStation[] = bikeStations,
) {
  const bounds = map.getBounds()
  return stations.filter((station) => bounds.contain(new maps.LatLng(station.lat, station.lng)))
}

export function groupVisibleBikeStations(
  maps: KakaoMaps,
  map: KakaoMapInstance,
  stations: BikeStation[] = bikeStations,
): BikeStationGroup[] {
  const visible = visibleBikeStations(maps, map, stations)
  if (map.getLevel() < BIKE_STATION_CLUSTER_LEVEL) {
    return visible.map((station) => ({
      stations: [station],
      center: { lat: station.lat, lng: station.lng },
    }))
  }

  const projection = map.getProjection()
  const groups = new Map<string, { stations: BikeStation[]; latTotal: number; lngTotal: number }>()
  visible.forEach((station) => {
    const point = projection.containerPointFromCoords(new maps.LatLng(station.lat, station.lng))
    const key = `${Math.floor(point.x / BIKE_STATION_CLUSTER_GRID_SIZE)}:${Math.floor(
      point.y / BIKE_STATION_CLUSTER_GRID_SIZE,
    )}`
    const group = groups.get(key)
    if (group) {
      group.stations.push(station)
      group.latTotal += station.lat
      group.lngTotal += station.lng
      return
    }
    groups.set(key, {
      stations: [station],
      latTotal: station.lat,
      lngTotal: station.lng,
    })
  })

  // ponytail: a fixed screen grid can split stations at cell edges; revisit only if that affects UX.
  return [...groups.values()].map((group) => ({
    stations: group.stations,
    center: {
      lat: group.latTotal / group.stations.length,
      lng: group.lngTotal / group.stations.length,
    },
  }))
}

export interface BikeStationClusterOverlay {
  element: HTMLButtonElement
  destroy(): void
}

export function zoomToBikeStationCluster(
  maps: KakaoMaps,
  map: KakaoMapInstance,
  group: BikeStationGroup,
) {
  map.setLevel(Math.max(BIKE_STATION_CLUSTER_LEVEL - 1, map.getLevel() - 2), {
    anchor: new maps.LatLng(group.center.lat, group.center.lng),
  })
}

export function createBikeStationClusterOverlay(
  maps: KakaoMaps,
  map: KakaoMapInstance,
  group: BikeStationGroup,
  onZoom: () => void,
): BikeStationClusterOverlay {
  const element = document.createElement('button')
  const label = `이 지역 따릉이 대여소 ${group.stations.length}개, 확대해서 보기`
  element.type = 'button'
  element.className = 'bike-station-cluster'
  element.setAttribute('aria-label', label)
  element.title = label
  element.textContent = String(group.stations.length)
  element.addEventListener('click', onZoom)
  const overlay = new maps.CustomOverlay({
    map,
    position: new maps.LatLng(group.center.lat, group.center.lng),
    content: element,
    clickable: true,
  })
  return {
    element,
    destroy() {
      element.removeEventListener('click', onZoom)
      overlay.setMap(null)
    },
  }
}
