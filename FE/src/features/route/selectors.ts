import type { Mode, Priority, Route } from './types'
export function getRoutes(routes: Route[], enabled: Mode[], priority: Priority) {
  const compare = (a: Route, b: Route) =>
    priority === 'calm'
      ? a.congestionPercent !== undefined && b.congestionPercent !== undefined
        ? a.congestionPercent - b.congestionPercent || a.minutes - b.minutes
        : a.congestionPercent !== undefined
          ? -1
          : b.congestionPercent !== undefined
            ? 1
            : a.minutes - b.minutes
      : a.minutes - b.minutes
  const visible = routes.filter((route) => route.modes.every((mode) => enabled.includes(mode)))
  return [
    ...visible.filter((r) => r.id === 'fast' || r.id === 'calm').sort(compare),
    ...visible.filter((r) => r.id !== 'fast' && r.id !== 'calm').sort(compare),
  ]
}
export function arrival(minutes: number, departedAt?: string) {
  const departure = departedAt ? new Date(departedAt) : null
  const start =
    departure && Number.isFinite(departure.getTime()) ? departure : new Date(2000, 0, 1, 9, 41)
  const arrivalAt = new Date(start.getTime() + Math.round(minutes * 60_000))
  return [
    String(arrivalAt.getHours()).padStart(2, '0'),
    String(arrivalAt.getMinutes()).padStart(2, '0'),
  ].join(':')
}
export function roundMinutes(minutes: number) {
  return Math.round(minutes)
}
export function remaining(route: Route, step: number) {
  return route.legs.slice(step).reduce((total, leg) => total + leg.minutes, 0)
}
