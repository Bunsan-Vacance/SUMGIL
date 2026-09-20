import { ArrowLeftRight, ChevronRight } from 'lucide-react'
import {
  clockTime,
  congestionGradeText,
  congestionPredictionFor,
  routeArrival,
  roundMinutes,
} from './selectors'
import type { Route } from './types'
import { compactLegs } from './LegList'
import { modeIcons } from './ModeIcon'
import { lineColor, lineTextColor } from './lineColor'
import { segmentCongestionGradeForLevel, segmentCongestionPresentation } from './segmentCongestion'
import { isTransitLeg, isTransferLeg, transitionLabel } from './transitions'

export default function RouteCard({
  route,
  comparison,
  busOptionCount,
  onDetail,
}: {
  route: Route
  comparison?: string
  busOptionCount?: number
  onDetail: () => void
}) {
  const displayLegs = compactLegs(route.legs)
  const hasCongestion = displayLegs.some(
    (leg) => isTransitLeg(leg) && leg.segmentCongestionLevel !== undefined,
  )
  const departure = clockTime(route.departedAt)
  const arrival = routeArrival(route.minutes, route.departedAt)
  const finalLeg = displayLegs.at(-1)
  const destination = finalLeg?.to?.name || finalLeg?.title.split(' → ').at(-1)
  const walkingMinutes = route.legs
    .filter((leg) => leg.mode === 'walk' && !leg.transfer && !leg.transitionType)
    .reduce((total, leg) => total + leg.minutes, 0)
  const facts = [
    route.totalDistanceMeters !== undefined
      ? `총 ${Math.round(route.totalDistanceMeters).toLocaleString('ko-KR')}m`
      : null,
    `환승 ${route.transfers ? `${route.transfers}회` : '없음'}`,
    walkingMinutes ? `도보 ${roundMinutes(walkingMinutes)}분` : null,
    busOptionCount && busOptionCount > 1 ? `버스 ${busOptionCount}개 노선` : null,
  ].filter((fact): fact is string => fact !== null)
  const prediction = congestionPredictionFor(route)
  const congestionGrade = prediction ? congestionGradeText(prediction.congestionGrade) : undefined
  const congestionLabel = prediction
    ? `혼잡도 예상 ${prediction.congestionPercent}%${congestionGrade ? ` · ${congestionGrade}` : ''}`
    : '예측 정보 없음'

  return (
    <button
      type="button"
      className="route-card"
      aria-label={[
        route.label,
        `${roundMinutes(route.minutes)}분`,
        congestionLabel,
        comparison,
        '상세 경로',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={onDetail}
    >
      <span className="route-card-topline">
        <span className="route-badge">{route.label}</span>
        <span className="route-card-actions">
          {route.source === 'MOCK' && <span className="route-source">샘플</span>}
          <ChevronRight className="route-card-chevron" size={20} aria-hidden="true" />
        </span>
      </span>
      <span className="route-card-main">
        <span className="route-card-details">
          <span className="route-time">
            <span>
              <b>{roundMinutes(route.minutes)}</b>분
            </span>
            <small>{departure ? `${departure} → ${arrival}` : '출발 시각 준비중입니다'}</small>
          </span>
          <span className="route-facts">{facts.join(' · ')}</span>
        </span>
        <span className="route-card-prediction" aria-label={congestionLabel}>
          {prediction ? (
            <>
              <small>혼잡도 예상</small>
              <strong>{prediction.congestionPercent}%</strong>
              {congestionGrade && <span>{congestionGrade}</span>}
            </>
          ) : (
            <span>예측 정보 없음</span>
          )}
        </span>
      </span>
      {comparison && <span className="route-comparison">{comparison}</span>}
      {hasCongestion && (
        <span className="route-segment-labels" aria-label="구간별 혼잡도">
          {displayLegs.map((leg, index) => {
            const congestion = isTransitLeg(leg)
              ? segmentCongestionPresentation(
                  segmentCongestionGradeForLevel(leg.segmentCongestionLevel),
                )
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
                backgroundColor: lineColor(leg),
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
      <span className="route-stops">
        {displayLegs
          .filter((leg) => !leg.transfer && leg.mode !== 'walk')
          .map((leg, index) => {
            const Icon = modeIcons[leg.mode]
            const station = leg.from?.name || leg.title.split(' → ')[0]
            return (
              <span className="route-stop" key={index}>
                <span className={`leg-icon ${leg.mode}`} style={{ color: lineColor(leg) }}>
                  <Icon size={17} aria-hidden="true" />
                </span>
                <strong>{station}</strong>
                <span className={`route-stop-line ${leg.mode}`}>
                  <i
                    className="route-line-dot"
                    style={{ backgroundColor: lineColor(leg) }}
                    hidden={!lineColor(leg)}
                  />
                  {leg.note}
                  {transitionLabel(leg.transitionType) &&
                    ` · ${transitionLabel(leg.transitionType)}`}
                </span>
              </span>
            )
          })}
        {destination && (
          <span className="route-stop route-stop-arrival">
            <span className="route-arrival-dot" aria-hidden="true" />
            <strong>{destination}</strong>
            <span className="route-stop-line">도착</span>
          </span>
        )}
      </span>
    </button>
  )
}
