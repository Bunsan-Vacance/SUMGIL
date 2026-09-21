import type { Leg, Route } from './types'
import { modeIcons } from './ModeIcon'
import { roundMinutes } from './selectors'
import { lineColor } from './lineColor'
import { segmentCongestionGradeForLeg, segmentCongestionPresentation } from './segmentCongestion'
import { isTransitLeg, transitionLabel } from './transitions'

function formatDistance(distanceMeters?: number) {
  if (distanceMeters === undefined) return '거리 준비중입니다'
  if (distanceMeters < 1000) return `${Math.round(distanceMeters)}m`
  return `${(distanceMeters / 1000).toFixed(distanceMeters >= 10000 ? 0 : 1)}km`
}

function formatCongestion(leg: Leg) {
  const grade = segmentCongestionGradeForLeg(leg)
  if (leg.segmentCongestionGrade && grade) {
    const presentation = segmentCongestionPresentation(grade)
    if (presentation) return `구간 예상 혼잡도 ${presentation.label}`
  }
  return leg.segmentCongestionLevel === undefined
    ? undefined
    : `구간 예상 혼잡도 ${leg.segmentCongestionLevel}%`
}

function sameBusOptions(left: Leg, right: Leg) {
  if (left.busRouteOptions === undefined && right.busRouteOptions === undefined) return true
  if (!left.busRouteOptions || !right.busRouteOptions) return false
  return JSON.stringify(left.busRouteOptions) === JSON.stringify(right.busRouteOptions)
}

export function compactLegs(legs: Leg[]) {
  return legs
    .reduce<Array<{ leg: Leg; count: number }>>((groups, leg) => {
      const previous = groups.at(-1)
      if (
        previous &&
        !previous.leg.transfer &&
        !leg.transfer &&
        !previous.leg.transitionType &&
        !leg.transitionType &&
        previous.leg.mode === leg.mode &&
        previous.leg.routeId === leg.routeId &&
        sameBusOptions(previous.leg, leg) &&
        previous.leg.segmentCongestionLevel === undefined &&
        leg.segmentCongestionLevel === undefined &&
        previous.leg.segmentCongestionGrade === undefined &&
        leg.segmentCongestionGrade === undefined
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

export default function LegList({
  route,
  compact = false,
  activeIndex,
}: {
  route: Route
  compact?: boolean
  /** Index in the original route.leg list, even when a compact list is rendered. */
  activeIndex?: number
}) {
  const legs = compact && activeIndex === undefined ? compactLegs(route.legs) : route.legs
  return (
    <ol className="leg-list">
      {legs.map((leg, index) => {
        const Icon = modeIcons[leg.mode]
        const legCongestion = isTransitLeg(leg) ? formatCongestion(leg) : undefined
        return (
          <li
            key={index}
            className={activeIndex === index ? 'is-active' : undefined}
            aria-current={activeIndex === index ? 'step' : undefined}
          >
            <span className={`leg-icon ${leg.mode}`} style={{ color: lineColor(leg) }}>
              <Icon size={18} />
            </span>
            <div>
              <strong>
                {activeIndex === index && <span className="leg-current">현재 단계</span>}
                {leg.title}
              </strong>
              <p>
                {leg.note} · {formatDistance(leg.distanceMeters)}
                {transitionLabel(leg.transitionType) && ` · ${transitionLabel(leg.transitionType)}`}
                {legCongestion && ` · ${legCongestion}`}
              </p>
            </div>
            <span>{roundMinutes(leg.minutes)}분</span>
          </li>
        )
      })}
    </ol>
  )
}
