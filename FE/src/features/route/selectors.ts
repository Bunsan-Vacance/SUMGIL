import type { Mode, Priority, Route } from './types'
export function getRoutes(routes: Route[], enabled: Mode[], priority: Priority) {
  const compare = (a: Route, b: Route) =>
    priority === 'calm' ? a.crowd - b.crowd || a.minutes - b.minutes : a.minutes - b.minutes
  const visible = routes.filter((route) => route.modes.every((mode) => enabled.includes(mode)))
  return [
    ...visible.filter((r) => r.id === 'fast' || r.id === 'calm').sort(compare),
    ...visible.filter((r) => r.id !== 'fast' && r.id !== 'calm').sort(compare),
  ]
}
export function arrival(minutes: number) {
  const total = 9 * 60 + 41 + minutes
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}
export function remaining(route: Route, step: number) {
  return route.legs.slice(step).reduce((total, leg) => total + leg.minutes, 0)
}
