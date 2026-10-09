import type { TrainArrival } from '../../api/guidance'

export interface ArrivalEntry {
  etaLabel: string
  etaMinutes: number
  arrivalTime: string
}

export interface DirectionArrivals {
  direction: string
  trains: ArrivalEntry[]
}

/** 방면별로 가장 빠른 열차를 묶는다. 이미 지난 열차는 제외하고 방면은 응답 등장 순서를 따른다. */
export function groupArrivalsByDirection(
  trains: TrainArrival[],
  now: Date,
  perDirection = 2,
): DirectionArrivals[] {
  const groups = new Map<string, Array<ArrivalEntry & { time: number }>>()
  for (const train of trains) {
    const time = new Date(train.arrivalTime).getTime()
    if (!Number.isFinite(time)) continue
    const diff = time - now.getTime()
    if (Math.round(diff / 60000) < 0) continue
    const etaMinutes = Math.round(diff / 60000)
    const entry = {
      etaLabel: etaMinutes < 1 ? '곧 도착' : `${etaMinutes}분 후`,
      etaMinutes,
      arrivalTime: train.arrivalTime,
      time,
    }
    const list = groups.get(train.direction)
    if (list) list.push(entry)
    else groups.set(train.direction, [entry])
  }
  return [...groups.entries()].map(([direction, list]) => ({
    direction,
    trains: list
      .sort((a, b) => a.time - b.time)
      .slice(0, perDirection)
      .map(({ etaLabel, etaMinutes, arrivalTime }) => ({ etaLabel, etaMinutes, arrivalTime })),
  }))
}

/** Asia/Seoul 기준 HH:mm 또는 HH:mm:ss. 잘못된 값은 빈 문자열이다. */
export function formatClock(iso: string | null, withSeconds: boolean): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (!Number.isFinite(date.getTime())) return ''
  return date.toLocaleTimeString('en-GB', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
    hourCycle: 'h23',
  })
}
