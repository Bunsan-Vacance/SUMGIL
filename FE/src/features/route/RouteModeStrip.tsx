import type { CSSProperties } from 'react'
import type { Leg } from './types'
import { compactLegs } from './LegList'
import { modeIcons } from './ModeIcon'
import { lineColor, lineTextColor } from './lineColor'
import { roundMinutes } from './selectors'
import { segmentCongestionGradeForLeg, segmentCongestionPresentation } from './segmentCongestion'
import { isTransitLeg, isTransferLeg, transitionLabel } from './transitions'

export default function RouteModeStrip({
  legs,
  showCongestionLabels = true,
}: {
  legs: Leg[]
  showCongestionLabels?: boolean
}) {
  const displayLegs = compactLegs(legs)
  const hasRide = displayLegs.some((leg) => leg.mode !== 'walk' && !isTransferLeg(leg))
  const segmentStyles: CSSProperties[] = displayLegs.map((leg) => {
    if (hasRide && (leg.mode === 'walk' || isTransferLeg(leg))) {
      // Walking only needs room for its time; brief transfers stay as a small gap.
      const width =
        isTransferLeg(leg) && leg.minutes < 2
          ? 8
          : 20 + String(roundMinutes(leg.minutes)).length * 6
      return { flexGrow: 0, flexBasis: `${width}px`, minWidth: 0 }
    }
    return {
      flexGrow: leg.minutes,
      minWidth: `min(44px, ${100 / Math.max(displayLegs.length, 1)}%)`,
    }
  })
  const hasCongestion = displayLegs.some(
    (leg) => isTransitLeg(leg) && segmentCongestionGradeForLeg(leg) !== undefined,
  )
  return (
    <>
      {showCongestionLabels && hasCongestion && (
        <span className="route-segment-labels" aria-label="구간별 혼잡도">
          {displayLegs.map((leg, index) => {
            const congestion = isTransitLeg(leg)
              ? segmentCongestionPresentation(segmentCongestionGradeForLeg(leg))
              : undefined
            const from = leg.from?.name || leg.title.split(' → ')[0]
            const to = leg.to?.name || leg.title.split(' → ').at(-1)
            const segment = [from, to].filter(Boolean).join(' → ') || leg.title
            return (
              <span
                className="route-segment-label"
                key={index}
                style={{ ...segmentStyles[index], color: congestion?.color }}
                title={
                  congestion
                    ? `${segment} 구간 혼잡도 ${congestion.label}`
                    : `${segment} 구간 혼잡도 정보 없음`
                }
                aria-label={
                  congestion
                    ? `${segment} 구간 혼잡도 ${congestion.label}`
                    : `${segment} 구간 혼잡도 정보 없음`
                }
              >
                {congestion?.label || ''}
              </span>
            )
          })}
        </span>
      )}
      <span className="mode-strip" aria-label="구간별 이동 시간">
        {displayLegs.map((leg, index) => {
          const transfer = isTransferLeg(leg)
          const compact = transfer || leg.mode === 'walk'
          const Icon = modeIcons[leg.mode]
          const label = `${transitionLabel(leg.transitionType) || (transfer ? '환승' : leg.note)} ${roundMinutes(leg.minutes)}분`
          return (
            <span
              key={index}
              className={`mode-strip-item ${transfer ? 'transfer' : leg.mode}`}
              style={{
                ...segmentStyles[index],
                backgroundColor: transfer || leg.mode === 'walk' ? 'transparent' : lineColor(leg),
                color: lineTextColor(leg),
              }}
              title={label}
              aria-label={label}
            >
              <span className="mode-strip-label">
                {!compact && <Icon size={13} aria-hidden="true" />}
                <span>
                  {!compact && transitionLabel(leg.transitionType) && (
                    <span className="mode-strip-transfer-label">
                      {transitionLabel(leg.transitionType) || '환승'}{' '}
                    </span>
                  )}
                  {roundMinutes(leg.minutes)}분
                </span>
              </span>
            </span>
          )
        })}
      </span>
    </>
  )
}
