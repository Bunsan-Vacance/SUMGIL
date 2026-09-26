import { ArrowLeftRight } from 'lucide-react'
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
                style={{ flexGrow: leg.minutes, color: congestion?.color }}
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
          const Icon = transfer ? ArrowLeftRight : modeIcons[leg.mode]
          return (
            <span
              key={index}
              className={`mode-strip-item ${transfer ? 'transfer' : leg.mode}`}
              style={{
                flexGrow: leg.minutes,
                backgroundColor: transfer || leg.mode === 'walk' ? 'transparent' : lineColor(leg),
                color: lineTextColor(leg),
              }}
              title={`${transitionLabel(leg.transitionType) || (transfer ? '환승' : leg.note)} ${roundMinutes(leg.minutes)}분`}
            >
              <span className="mode-strip-label">
                <Icon size={13} aria-hidden="true" />
                <span>
                  {(transitionLabel(leg.transitionType) || (transfer ? '환승' : '')) && (
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
