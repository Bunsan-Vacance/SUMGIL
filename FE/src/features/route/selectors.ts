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
  const visible = routes.filter((route) =>
    route.modes.every((mode) => mode === 'walk' || enabled.includes(mode)),
  )
  return [
    ...visible.filter((r) => r.id === 'fast' || r.id === 'calm').sort(compare),
    ...visible.filter((r) => r.id !== 'fast' && r.id !== 'calm').sort(compare),
  ]
}
export function arrival(minutes: number, departedAt?: string) {
  const trimmed = departedAt?.trim()
  const hasTimeZone = trimmed ? /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed) : false
  const departure = trimmed
    ? new Date(
        hasTimeZone ? trimmed : `${trimmed.includes('T') ? trimmed : `${trimmed}T00:00:00`}+09:00`,
      )
    : null
  const elapsedMinutes = Math.round(minutes)
  if (!departure || !Number.isFinite(departure.getTime())) {
    const totalMinutes = (9 * 60 + 41 + elapsedMinutes) % (24 * 60)
    const normalizedMinutes = (totalMinutes + 24 * 60) % (24 * 60)
    return [
      String(Math.floor(normalizedMinutes / 60)).padStart(2, '0'),
      String(normalizedMinutes % 60).padStart(2, '0'),
    ].join(':')
  }
  const arrivalAt = new Date(departure.getTime() + elapsedMinutes * 60_000)
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(arrivalAt)
  const hour = parts.find((part) => part.type === 'hour')?.value || '00'
  const minute = parts.find((part) => part.type === 'minute')?.value || '00'
  return [hour, minute].join(':')
}
export function roundMinutes(minutes: number) {
  return Math.round(minutes)
}
export function remaining(route: Route, step: number) {
  return route.legs.slice(step).reduce((total, leg) => total + leg.minutes, 0)
}
