import { ChevronRight } from 'lucide-react'
import {
  clockTime,
  congestionPredictionPresentation,
  congestionPredictionFor,
  routeArrival,
  roundMinutes,
} from './selectors'
import type { Route } from './types'
import { compactLegs } from './LegList'
import { modeIcons } from './ModeIcon'
import { lineColor } from './lineColor'
import RouteModeStrip from './RouteModeStrip'
import { isTransitLeg, transitionLabel } from './transitions'
import { segmentCongestionGradeForLeg, segmentCongestionPresentation } from './segmentCongestion'
import { bikeRouteAvailabilityMessage, type BikeRouteAvailability } from './bikeAvailability'
import { isBikeStockMockEnabled } from '../../api/repositories'

function isBikeRoute(route: Route) {
  return route.legs.some((leg) => leg.mode === 'bike')
}

function availabilityLabel(availability: BikeRouteAvailability) {
  const message = bikeRouteAvailabilityMessage(availability.status)
  if (!message || availability.status === 'checking') return message
  if (availability.status !== 'unknown') return message
  if (!availability.stockUpdatedAt) return `${message} · 기준 시각 확인 불가`
  const time = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(availability.stockUpdatedAt))
  const basis = availability.stockBasis === 'return' ? '반납 재고' : '대여 재고'
  return `${message} · ${basis} 마지막 확인 ${time}`
}

export default function RouteCard({
  route,
  comparison,
  selected = false,
  recommendations = [],
  bikeAvailability,
  onDetail,
}: {
  route: Route
  comparison?: string
  selected?: boolean
  recommendations?: Array<'fast' | 'calm'>
  bikeAvailability?: BikeRouteAvailability
  onDetail: () => void
}) {
  const displayLegs = compactLegs(route.legs)
  const departure = clockTime(route.departedAt)
  const arrival = routeArrival(route.minutes, route.departedAt)
  const finalLeg = displayLegs.at(-1)
  const destination = finalLeg?.to?.name || finalLeg?.title.split(' → ').at(-1)
  const prediction = congestionPredictionFor(route)
  const predictionPresentation = congestionPredictionPresentation(prediction, route.legs)
  const congestionGrade = predictionPresentation?.label
  const congestionLabel = prediction
    ? `혼잡도 예상 ${congestionGrade ?? '정보 없음'}`
    : '예측 정보 없음'
  const recommendationLabels = recommendations.map((recommendation) =>
    recommendation === 'fast' ? '가장 빠른 경로' : '덜 붐비는 경로',
  )
  const featuredClass = recommendations.length
    ? `route-card-featured route-card-featured-${recommendations.length > 1 ? 'both' : recommendations[0]}`
    : ''
  const availabilityStatus = isBikeRoute(route)
    ? (bikeAvailability?.status ?? 'checking')
    : undefined
  const baseAvailabilityNotice =
    availabilityStatus && bikeAvailability
      ? availabilityLabel({ ...bikeAvailability, status: availabilityStatus })
      : availabilityStatus
        ? bikeRouteAvailabilityMessage(availabilityStatus)
        : null
  const availabilityNotice = baseAvailabilityNotice
    ? `${baseAvailabilityNotice}${
        isBikeStockMockEnabled && isBikeRoute(route) && route.source !== 'MOCK' ? ' · 샘플' : ''
      }`
    : null

  return (
    <button
      type="button"
      className={`route-card ${featuredClass} ${selected ? 'route-card-selected' : ''}`.trim()}
      aria-current={selected ? 'true' : undefined}
      aria-label={[
        route.label,
        `${roundMinutes(route.minutes)}분`,
        congestionLabel,
        availabilityNotice,
        ...recommendationLabels,
        comparison,
        '상세 경로',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={onDetail}
    >
      <span className="route-card-topline">
        <span className="route-card-heading">
          <span className="route-badge">{route.label}</span>
          {recommendationLabels.length > 0 && (
            <span className="route-recommendation-badges" aria-label="추천 기준">
              {recommendationLabels.map((label, index) => (
                <span
                  className={`route-recommendation-badge ${recommendations[index]}`}
                  key={label}
                >
                  {label}
                </span>
              ))}
            </span>
          )}
        </span>
        <span className="route-card-actions">
          {route.source === 'MOCK' && <span className="route-source">샘플</span>}
          <ChevronRight className="route-card-chevron" size={20} aria-hidden="true" />
        </span>
      </span>
      {availabilityNotice && (
        <span
          className={`route-bike-availability route-bike-availability-${availabilityStatus}`}
          role={
            availabilityStatus === 'rental-unavailable' ||
            availabilityStatus === 'rental-unavailable-current' ||
            availabilityStatus === 'return-crowded'
              ? 'status'
              : undefined
          }
        >
          {availabilityNotice}
        </span>
      )}
      <span className="route-card-main">
        <span className="route-card-details">
          <span className="route-time">
            <span>
              <b>{roundMinutes(route.minutes)}</b>분
            </span>
            <small>{departure ? `${departure} → ${arrival}` : '출발 시각 준비중입니다'}</small>
          </span>
        </span>
        <span className="route-card-prediction" aria-label={congestionLabel}>
          {prediction ? (
            <>
              <small>혼잡도 예상</small>
              <strong style={{ color: predictionPresentation?.color }}>
                {congestionGrade ?? '정보 없음'}
              </strong>
            </>
          ) : (
            <span>예측 정보 없음</span>
          )}
        </span>
      </span>
      {comparison && <span className="route-comparison">{comparison}</span>}
      <RouteModeStrip legs={route.legs} showCongestionLabels={false} />
      <span className="route-stops">
        {displayLegs
          .filter((leg) => !leg.transfer && leg.mode !== 'walk')
          .map((leg, index) => {
            const Icon = modeIcons[leg.mode]
            const station = leg.from?.name || leg.title.split(' → ')[0]
            const congestion = isTransitLeg(leg)
              ? segmentCongestionPresentation(segmentCongestionGradeForLeg(leg))
              : undefined
            const arrivalStation = leg.to?.name || leg.title.split(' → ').at(-1)
            return (
              <span className="route-stop" key={index}>
                <span className={`leg-icon ${leg.mode}`} style={{ color: lineColor(leg) }}>
                  <Icon size={17} aria-hidden="true" />
                </span>
                <strong>{station}</strong>
                <span className="route-stop-meta">
                  {congestion && (
                    <span
                      className="route-stop-congestion"
                      style={{ color: congestion.color }}
                      aria-label={`${station} → ${arrivalStation} 구간 혼잡도 ${congestion.label}`}
                    >
                      {congestion.label}
                    </span>
                  )}
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
