import type { Leg, Route, RouteEndpoint } from './types'

export interface RouteGroup {
  representative: Route
  variants: Route[]
}

function endpointKey(endpoint?: RouteEndpoint) {
  if (!endpoint) return undefined
  if (endpoint.id) return `id:${endpoint.id}`
  if (endpoint.lat !== undefined && endpoint.lng !== undefined) {
    return `coord:${endpoint.lat},${endpoint.lng}:${endpoint.name || ''}`
  }
  return undefined
}

function legKey(leg: Leg) {
  const from = endpointKey(leg.from)
  const to = endpointKey(leg.to)
  if (!from || !to) return undefined
  if (leg.mode === 'subway' && !leg.routeId) return undefined
  const routeId = leg.mode === 'bus' ? '' : leg.routeId || ''
  return [
    leg.mode,
    leg.transfer ? 'transfer' : '',
    leg.transitionType || '',
    from,
    to,
    routeId,
  ].join(':')
}

function groupingKey(route: Route) {
  if (!route.legs.some((leg) => leg.mode === 'bus')) return undefined
  const legs = route.legs.map(legKey)
  return legs.every((key): key is string => !!key) ? legs.join('|') : undefined
}

/** Groups only routes with the same endpoints, modes, and non-bus lines. */
export function groupRoutes(routes: Route[]): RouteGroup[] {
  const groups = new Map<string, RouteGroup>()
  return routes.reduce<RouteGroup[]>((result, route) => {
    const key = groupingKey(route)
    if (!key) {
      result.push({ representative: route, variants: [route] })
      return result
    }
    const group = groups.get(key)
    if (group) {
      group.variants.push(route)
      return result
    }
    const created = { representative: route, variants: [route] }
    groups.set(key, created)
    result.push(created)
    return result
  }, [])
}

function busLabel(leg: Leg) {
  const label = leg.note.trim()
  if (label && label !== '버스') return label
  return leg.routeId?.trim() || '버스'
}

export function busLabels(route: Route) {
  return route.legs.filter((leg) => leg.mode === 'bus').map(busLabel)
}

export function formatBusLabel(label: string) {
  return /^\d+$/.test(label) ? `${label}번` : label
}

export function busRouteOptions(routes: Route[]) {
  const options: Array<{ route: Route; labels: string[] }> = []
  const seen = new Set<string>()
  routes.forEach((route) => {
    const labels = busLabels(route)
    if (!labels.length) return
    const key = route.legs
      .filter((leg) => leg.mode === 'bus')
      .map((leg, index) => `${index}:${leg.routeId || ''}:${busLabel(leg)}`)
      .join('|')
    if (seen.has(key)) return
    seen.add(key)
    options.push({ route, labels })
  })
  return options
}
