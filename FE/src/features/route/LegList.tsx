import type { Leg, Route } from './types'
import { modeIcons } from './ModeIcon'
import { roundMinutes } from './selectors'
import { lineColor } from './lineColor'
import { useRouteCongestion } from './useCongestion'

function formatDistance(distanceMeters?: number) {
  if (distanceMeters === undefined) return '거리 준비중입니다'
  if (distanceMeters < 1000) return `${Math.round(distanceMeters)}m`
  return `${(distanceMeters / 1000).toFixed(distanceMeters >= 10000 ? 0 : 1)}km`
}

function formatCongestion(level?: number) {
  if (level === undefined) return '출발역 통계 혼잡도 준비중입니다'
  return `출발역 통계 혼잡도 ${Number.isInteger(level) ? level : level.toFixed(1)}%`
}

export function compactLegs(legs: Leg[]) {
  return legs
    .reduce<Array<{ leg: Leg; count: number }>>((groups, leg) => {
      const previous = groups.at(-1)
      if (
        previous &&
        !previous.leg.transfer &&
        !leg.transfer &&
        previous.leg.mode === leg.mode &&
        previous.leg.routeId === leg.routeId
      ) {
        const from = previous.leg.from?.name || previous.leg.title.split(' → ')[0]
        const to = leg.to?.name || leg.title.split(' → ').at(-1)
        previous.leg = {
          ...previous.leg,
          title: from && to ? `${from} → ${to}` : previous.leg.title,
          minutes: previous.leg.minutes + leg.minutes,
          ...(previous.leg.distanceMeters !== undefined && leg.distanceMeters !== undefined
            ? { distanceMeters: previous.leg.distanceMeters + leg.distanceMeters }
            : { distanceMeters: undefined }),
          to: leg.to,
        }
        previous.count += 1
        return groups
      }
      groups.push({ leg, count: 1 })
      return groups
    }, [])
    .map(({ leg }) => leg)
}

export default function LegList({ route, compact = false }: { route: Route; compact?: boolean }) {
  const legs = compact ? compactLegs(route.legs) : route.legs
  const congestion = useRouteCongestion(legs, route.departedAt)
  return (
    <ol className="leg-list">
      {legs.map((leg, index) => {
        const Icon = modeIcons[leg.mode]
        const legCongestion = leg.mode === 'subway' ? congestion[index] : undefined
        return (
          <li key={index}>
            <span className={`leg-icon ${leg.mode}`} style={{ color: lineColor(leg) }}>
              <Icon size={18} />
            </span>
            <div>
              <strong>{leg.title}</strong>
              <p>
                {leg.note} · {formatDistance(leg.distanceMeters)}
                {legCongestion && <> · {formatCongestion(legCongestion.level)}</>}
              </p>
            </div>
            <span>{roundMinutes(leg.minutes)}분</span>
          </li>
        )
      })}
    </ol>
  )
}
