import type {
  CongestionGrade,
  CongestionPrediction,
  CongestionPredictionBasis,
  Mode,
  Priority,
  Route,
} from './types'

function predictionPercent(route: Route, now = new Date()) {
  const prediction = congestionPredictionFor(route, now)
  return prediction?.congestionPercent ?? undefined
}

export function getRoutes(routes: Route[], enabled: Mode[], priority: Priority) {
  const compare = (a: Route, b: Route) => {
    if (priority === 'fast') return a.minutes - b.minutes
    const aPercent = predictionPercent(a)
    const bPercent = predictionPercent(b)
    if (aPercent !== undefined && bPercent !== undefined) {
      return aPercent - bPercent || a.minutes - b.minutes
    }
    if (aPercent !== undefined) return -1
    if (bPercent !== undefined) return 1
    if (a.routeType === 'LOW_CONGESTION') return -1
    if (b.routeType === 'LOW_CONGESTION') return 1
    return a.minutes - b.minutes
  }
  const visible = routes.filter((route) =>
    route.modes.every((mode) => mode === 'walk' || enabled.includes(mode)),
  )
  return [...visible].sort(compare)
}

export function parseDeparture(value?: string) {
  const trimmed = value?.trim()
  if (!trimmed) return null
  const hasTimeZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed)
  const date = new Date(
    hasTimeZone ? trimmed : `${trimmed.includes('T') ? trimmed : `${trimmed}T00:00:00`}+09:00`,
  )
  return Number.isFinite(date.getTime()) ? date : null
}

function seoulDay(value: Date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(value)
  const valueOf = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value
  const year = valueOf('year')
  const month = valueOf('month')
  const day = valueOf('day')
  return year && month && day ? Date.UTC(+year, +month - 1, +day) : NaN
}

export function isCongestionPredictionDate(value?: string, now = new Date()) {
  const departure = parseDeparture(value)
  if (!departure) return false
  const difference = (seoulDay(departure) - seoulDay(now)) / (24 * 60 * 60 * 1000)
  return Number.isInteger(difference) && difference >= 0 && difference <= 3
}

export function congestionPredictionFor(
  route: Route,
  now = new Date(),
): (CongestionPrediction & { congestionPercent: number }) | undefined {
  const prediction = route.congestionPrediction
  return isCongestionPredictionDate(route.departedAt, now) &&
    prediction &&
    prediction.dataStatus === 'AVAILABLE' &&
    typeof prediction.congestionPercent === 'number' &&
    Number.isFinite(prediction.congestionPercent) &&
    prediction.congestionPercent >= 0
    ? (prediction as CongestionPrediction & { congestionPercent: number })
    : undefined
}

const congestionPercentFormatter = new Intl.NumberFormat('ko-KR', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

export function formatCongestionPercent(value: number) {
  return congestionPercentFormatter.format(value)
}

export function congestionGradeText(value: CongestionGrade | null) {
  return value === 'LOW'
    ? '여유'
    : value === 'MEDIUM'
      ? '보통'
      : value === 'HIGH'
        ? '혼잡'
        : undefined
}

export function congestionBasisText(value: CongestionPredictionBasis | null) {
  return value === 'RECENT_7D'
    ? '최근 7일 데이터 기반'
    : value === 'PARTIAL'
      ? '일부 기간 데이터 기반'
      : value === 'WEEKDAY_AVERAGE'
        ? '요일 평균 기준'
        : undefined
}
export function clockTime(value?: string) {
  const date = parseDeparture(value)
  if (!date) return undefined
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const hour = parts.find((part) => part.type === 'hour')?.value
  const minute = parts.find((part) => part.type === 'minute')?.value
  return hour && minute ? `${hour}:${minute}` : undefined
}
export function routeArrival(minutes: number, departedAt?: string) {
  return clockTime(departedAt) ? arrival(minutes, departedAt) : '준비중입니다'
}
export function arrival(minutes: number, departedAt?: string) {
  const departure = parseDeparture(departedAt)
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
