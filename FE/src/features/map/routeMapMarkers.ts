import type { KakaoMapInstance, KakaoMaps, MapOverlay } from '../../lib/kakao/sdk'
import type { GeometryLineString, Leg, Place, Route, RouteEndpoint } from '../route/types'
import { lineColor } from '../route/lineColor'

export type RouteEndpointRole = '승차' | '환승' | '하차'
export type BikeEndpointRole = '대여' | '반납'
type LocatedRouteEndpoint = RouteEndpoint & { lat: number; lng: number }

export interface RouteEndpointCandidate {
  endpoint: LocatedRouteEndpoint
  roles: RouteEndpointRole[]
  bikeRoles?: BikeEndpointRole[]
}

const ROUTE_LINE_STYLES = {
  subway: { strokeColor: '#6379bd', strokeStyle: 'solid' },
  bus: { strokeColor: '#2f80c0', strokeStyle: 'solid' },
  bike: { strokeColor: '#2f7a59', strokeStyle: 'solid' },
  walk: { strokeColor: '#6379bd', strokeStyle: 'solid' },
  transfer: { strokeColor: '#5d6873', strokeStyle: 'dashed' },
} as const

export interface RouteLineEntry {
  coordinates: GeometryLineString
  style: ReturnType<typeof routeLineStyle>
}

export function routeLineStyle(leg: Leg) {
  if (leg.transfer) return ROUTE_LINE_STYLES.transfer
  const color = lineColor(leg)
  if (color) return { strokeColor: color, strokeStyle: 'solid' as const }
  return ROUTE_LINE_STYLES[leg.mode]
}

function validPath(maps: KakaoMaps, coordinates: GeometryLineString) {
  return coordinates
    .filter(
      ([lng, lat]) =>
        Number.isFinite(lng) &&
        Number.isFinite(lat) &&
        lng >= -180 &&
        lng <= 180 &&
        lat >= -90 &&
        lat <= 90,
    )
    .map(([lng, lat]) => new maps.LatLng(lat, lng))
}

export interface RouteSvgOverlay extends MapOverlay {
  element: SVGSVGElement
  destroy(): void
}

export function createRouteSvgOverlay(
  maps: KakaoMaps,
  map: KakaoMapInstance,
  entries: RouteLineEntry[],
): RouteSvgOverlay {
  const AbstractOverlay = maps.AbstractOverlay
  class SvgRouteOverlay extends AbstractOverlay {
    readonly element = document.createElementNS('http://www.w3.org/2000/svg', 'svg')

    constructor() {
      super()
      this.element.classList.add('route-svg-overlay')
      this.element.setAttribute('aria-hidden', 'true')
      this.element.setAttribute('focusable', 'false')
      this.element.style.pointerEvents = 'none'
      this.element.style.position = 'absolute'
      this.element.style.inset = '0'
      this.element.style.width = '1px'
      this.element.style.height = '1px'
      this.element.style.overflow = 'visible'
      this.element.style.zIndex = '5'
    }

    onAdd() {
      this.getPanels().overlayLayer.appendChild(this.element)
      this.draw()
    }

    onRemove() {
      this.element.remove()
    }

    draw() {
      const projection = this.getProjection()
      this.element.replaceChildren()
      entries.forEach(({ coordinates, style }) => {
        const path = validPath(maps, coordinates)
        if (path.length < 2) return
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline')
        const points = path
          .map((point) => {
            const pixel = projection.pointFromCoords(point)
            return `${pixel.x},${pixel.y}`
          })
          .join(' ')
        line.setAttribute('points', points)
        line.setAttribute('fill', 'none')
        line.setAttribute('stroke', style.strokeColor)
        line.setAttribute('stroke-width', '5')
        line.setAttribute('stroke-opacity', '0.85')
        line.setAttribute('stroke-linecap', 'round')
        line.setAttribute('stroke-linejoin', 'round')
        if (style.strokeStyle === 'dashed') line.setAttribute('stroke-dasharray', '8 6')
        this.element.appendChild(line)
      })
    }
  }

  const overlay = new SvgRouteOverlay()
  overlay.setMap(map)
  return {
    element: overlay.element,
    setMap(nextMap) {
      overlay.setMap(nextMap)
    },
    destroy() {
      overlay.setMap(null)
    },
  }
}

function hasCoordinates(endpoint: RouteEndpoint | undefined): endpoint is RouteEndpoint & {
  lat: number
  lng: number
} {
  return (
    endpoint?.lat !== undefined &&
    endpoint.lng !== undefined &&
    Number.isFinite(endpoint.lat) &&
    Number.isFinite(endpoint.lng) &&
    endpoint.lat >= -90 &&
    endpoint.lat <= 90 &&
    endpoint.lng >= -180 &&
    endpoint.lng <= 180
  )
}

function endpointKey(endpoint: LocatedRouteEndpoint) {
  if (endpoint.id?.trim()) return `id:${endpoint.id.trim()}`
  return `point:${endpoint.lat.toFixed(6)}:${endpoint.lng.toFixed(6)}`
}

export function getRouteEndpointCandidates(route: Route): RouteEndpointCandidate[] {
  const candidates = new Map<
    string,
    {
      endpoint: LocatedRouteEndpoint
      roles: Set<RouteEndpointRole>
      bikeRoles: Set<BikeEndpointRole>
    }
  >()
  const existingCandidate = (endpoint: LocatedRouteEndpoint) =>
    candidates.get(endpointKey(endpoint))
  const add = (role: RouteEndpointRole, endpoint: RouteEndpoint | undefined) => {
    if (!hasCoordinates(endpoint)) return
    const key = endpointKey(endpoint)
    const existing = candidates.get(key)
    if (existing) {
      existing.roles.add(role)
      return
    }
    candidates.set(key, { endpoint, roles: new Set([role]), bikeRoles: new Set() })
  }
  const addBike = (role: BikeEndpointRole, endpoint: RouteEndpoint | undefined) => {
    if (!hasCoordinates(endpoint)) return
    const key = endpointKey(endpoint)
    const existing = existingCandidate(endpoint)
    if (existing) {
      existing.bikeRoles.add(role)
      return
    }
    candidates.set(key, { endpoint, roles: new Set(), bikeRoles: new Set([role]) })
  }
  const transitLegs = route.legs.filter(
    (leg) => (leg.mode === 'subway' || leg.mode === 'bus') && !leg.transfer,
  )
  add('승차', transitLegs[0]?.from)
  add('하차', transitLegs.at(-1)?.to)
  route.legs
    .filter((leg) => leg.transfer)
    .forEach((leg) => {
      add('환승', leg.from)
      add('환승', leg.to)
    })
  transitLegs.slice(1).forEach((leg, index) => {
    const previous = transitLegs[index]
    if (previous.routeId !== leg.routeId || previous.mode !== leg.mode) {
      add('환승', hasCoordinates(leg.from) ? leg.from : previous.to)
    }
  })
  let bikeStart: Leg | undefined
  route.legs.forEach((leg, index) => {
    if (leg.mode === 'bike' && !bikeStart) {
      bikeStart = leg
      return
    }
    if (leg.mode === 'bike') return
    if (bikeStart) {
      addBike('대여', bikeStart.from)
      addBike('반납', route.legs[index - 1]?.to)
      bikeStart = undefined
    }
  })
  if (bikeStart) addBike('대여', bikeStart.from)
  if (bikeStart) addBike('반납', route.legs.at(-1)?.to)
  return [...candidates.values()].map(({ endpoint, roles, bikeRoles }) => ({
    endpoint,
    roles: [...roles],
    ...(bikeRoles.size ? { bikeRoles: [...bikeRoles] } : {}),
  }))
}

export function routeEndpointPlace(candidate: RouteEndpointCandidate): Place {
  if (candidate.bikeRoles?.length) {
    const label = candidate.bikeRoles.map((role) => `따릉이 ${role}`).join(' · ')
    return {
      id: `route-endpoint:${endpointKey(candidate.endpoint)}`,
      name: candidate.endpoint.name?.trim() || '따릉이 대여소',
      address: label,
      kind: '따릉이 대여소',
      lat: candidate.endpoint.lat,
      lng: candidate.endpoint.lng,
    }
  }
  const firstRole = candidate.roles[0] || '환승'
  const displayName = candidate.endpoint.name?.trim() || `${firstRole} 지점`
  const key = endpointKey(candidate.endpoint)
  return {
    id: `route-endpoint:${key}`,
    name: displayName,
    address: candidate.roles.join(' · '),
    kind: firstRole,
    lat: candidate.endpoint.lat,
    lng: candidate.endpoint.lng,
  }
}

export interface RouteEndpointOverlay {
  element: HTMLButtonElement
  destroy(): void
}

export function createRouteEndpointOverlay(
  maps: KakaoMaps,
  map: KakaoMapInstance,
  candidate: RouteEndpointCandidate,
  onSelect: (place: Place) => void,
): RouteEndpointOverlay {
  const place = routeEndpointPlace(candidate)
  const roleLabel = candidate.roles.join(' · ')
  const label = `${place.name} · ${roleLabel}`
  const element = document.createElement('button')
  element.type = 'button'
  element.className = `route-endpoint-marker route-endpoint-${place.kind}`
  element.setAttribute('aria-label', label)
  element.title = label
  element.textContent = roleLabel
  const handleClick = () => onSelect(place)
  element.addEventListener('click', handleClick)
  const overlay = new maps.CustomOverlay({
    map,
    position: new maps.LatLng(candidate.endpoint.lat, candidate.endpoint.lng),
    content: element,
    clickable: true,
    zIndex: 10,
  })
  return {
    element,
    destroy() {
      element.removeEventListener('click', handleClick)
      overlay.setMap(null)
    },
  }
}
