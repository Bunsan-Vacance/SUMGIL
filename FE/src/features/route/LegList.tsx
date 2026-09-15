import type { Leg, Route } from './types'
import { modeIcons } from './ModeIcon'
import { roundMinutes } from './selectors'
import { lineColor } from './lineColor'

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
  return (
    <ol className="leg-list">
      {legs.map((leg, index) => {
        const Icon = modeIcons[leg.mode]
        return (
          <li key={index}>
            <span className={`leg-icon ${leg.mode}`} style={{ color: lineColor(leg) }}>
              <Icon size={18} />
            </span>
            <div>
              <strong>{leg.title}</strong>
              <p>{leg.note}</p>
            </div>
            <span>{roundMinutes(leg.minutes)}분</span>
          </li>
        )
      })}
    </ol>
  )
}
