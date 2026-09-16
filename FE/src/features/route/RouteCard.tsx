import { ArrowLeftRight, ChevronRight, UsersRound } from 'lucide-react'
import { clockTime, routeArrival, roundMinutes } from './selectors'
import type { Route } from './types'
import { compactLegs } from './LegList'
import { modeIcons } from './ModeIcon'
import { lineColor, lineTextColor } from './lineColor'

export default function RouteCard({
  route,
  comparison,
  onDetail,
}: {
  route: Route
  comparison?: string
  onDetail: () => void
}) {
  const displayLegs = compactLegs(route.legs)
  const departure = clockTime(route.departedAt)
  const arrival = routeArrival(route.minutes, route.departedAt)
  const finalLeg = displayLegs.at(-1)
  const destination = finalLeg?.to?.name || finalLeg?.title.split(' → ').at(-1)
  const walkingMinutes = route.legs
    .filter((leg) => leg.mode === 'walk' && !leg.transfer)
    .reduce((total, leg) => total + leg.minutes, 0)
  const facts = [
    route.totalDistanceMeters !== undefined
      ? `총 ${Math.round(route.totalDistanceMeters).toLocaleString('ko-KR')}m`
      : null,
    `환승 ${route.transfers ? `${route.transfers}회` : '없음'}`,
    walkingMinutes ? `도보 ${roundMinutes(walkingMinutes)}분` : null,
    route.congestionPercent === undefined ? '혼잡도 준비중입니다' : null,
  ].filter((fact): fact is string => fact !== null)
  const congestion =
    route.congestionPercent === undefined
      ? '혼잡도 준비중입니다'
      : `혼잡도 ${Math.round(route.congestionPercent)}%`

  return (
    <button
      type="button"
      className="route-card"
      aria-label={[
        route.label,
        `${roundMinutes(route.minutes)}분`,
        congestion,
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
          {route.congestionPercent !== undefined && (
            <span className="route-card-congestion">
              <UsersRound size={14} aria-hidden="true" />
              혼잡도 {Math.round(route.congestionPercent)}%
            </span>
          )}
          <ChevronRight className="route-card-chevron" size={20} aria-hidden="true" />
        </span>
      </span>
      <span className="route-time">
        <span>
          <b>{roundMinutes(route.minutes)}</b>분
        </span>
        <small>{departure ? `${departure} → ${arrival}` : '출발 시각 준비중입니다'}</small>
      </span>
      <span className="route-facts">{facts.join(' · ')}</span>
      {comparison && <span className="route-comparison">{comparison}</span>}
      <span className="mode-strip" aria-label="구간별 이동 시간">
        {displayLegs.map((leg, index) => {
          const Icon = leg.transfer ? ArrowLeftRight : modeIcons[leg.mode]
          return (
            <span
              key={index}
              className={`mode-strip-item ${leg.transfer ? 'transfer' : leg.mode}`}
              style={{
                flexGrow: leg.minutes,
                backgroundColor: lineColor(leg),
                color: lineTextColor(leg),
              }}
              title={`${leg.transfer ? '환승' : leg.note} ${roundMinutes(leg.minutes)}분`}
            >
              <span className="mode-strip-label">
                <Icon size={13} aria-hidden="true" />
                <span>
                  {leg.transfer && <span className="mode-strip-transfer-label">환승 </span>}
                  {roundMinutes(leg.minutes)}분
                </span>
              </span>
            </span>
          )
        })}
      </span>
      <span className="route-stops">
        {displayLegs
          .filter((leg) => !leg.transfer)
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
