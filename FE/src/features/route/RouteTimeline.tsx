import './RouteTimeline.css'
import type { CSSProperties } from 'react'
import { useEffect, useRef } from 'react'
import { Footprints } from 'lucide-react'
import type { Leg, Route } from './types'
import { roundMinutes } from './selectors'
import { lineColor } from './lineColor'
import { busOptionLabel } from './routeGrouping'
import { segmentCongestionGradeForLeg, segmentCongestionPresentation } from './segmentCongestion'
import { isTransitLeg, transitionLabel } from './transitions'
import { modeIcons } from './ModeIcon'

function distanceLabel(value?: number) {
  if (value === undefined || !Number.isFinite(value)) return undefined
  return value < 1000
    ? `${Math.round(value)}m`
    : `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}km`
}

function stationName(leg: Leg, side: 'from' | 'to') {
  if (leg[side]?.name) return leg[side]?.name
  const path = [leg.title, leg.note].find((text) => text.includes(' → '))
  return path?.split(' → ').at(side === 'from' ? 0 : -1)
}

// A note can contain intermediate stops or direction: only suppress the exact endpoint pair.
function isEndpointPair(text: string, leg: Leg) {
  const names = text.split('→').map((name) => name.trim())
  return (
    names.length === 2 &&
    names[0] === stationName(leg, 'from') &&
    names[1] === stationName(leg, 'to')
  )
}

function transitCopy(leg: Leg) {
  const copy = [...new Set([leg.title, leg.note])].filter(
    (text) => text && text !== '이동 구간' && !isEndpointPair(text, leg),
  )
  if (leg.mode === 'bike')
    return {
      label: '따릉이',
      detail: copy.filter((text) => text !== '따릉이' && text !== '자전거').join(' · '),
    }
  if (leg.mode === 'bus' && leg.busRouteOptions?.length) {
    const optionNames = leg.busRouteOptions
      .map((option) => option.routeName || option.routeId)
      .join(' · ')
    return {
      label: leg.busRouteOptions.length === 1 ? busOptionLabel(leg.busRouteOptions[0]) : '버스',
      detail: copy.filter((text) => text !== optionNames && text !== '버스').join(' · '),
    }
  }
  return {
    label: copy[0] || (leg.mode === 'subway' ? '지하철' : '버스'),
    detail: copy.slice(1).join(' · '),
  }
}

function SegmentMeta({ leg, riding = false }: { leg: Leg; riding?: boolean }) {
  const distance = distanceLabel(leg.distanceMeters)
  const label = riding
    ? '이동'
    : transitionLabel(leg.transitionType) || (leg.transfer ? '환승' : '도보')
  return (
    <div className="route-timeline-meta">
      <span>
        {label}
        {distance ? ` ${distance}` : ''}
      </span>
      <strong>{roundMinutes(leg.minutes)}분</strong>
    </div>
  )
}

function Stop({
  leg,
  side,
  endpoint,
}: {
  leg: Leg
  side: 'from' | 'to'
  endpoint?: '출발' | '도착'
}) {
  const boarding = side === 'from'
  const Icon = boarding ? modeIcons[leg.mode] : Footprints
  const kind = leg.mode === 'bike' ? (boarding ? '대여' : '반납') : boarding ? '승차' : '하차'
  return (
    <div className={`route-timeline-stop ${boarding ? 'is-boarding' : 'is-alighting'}`}>
      <span className="route-timeline-stop-marker" aria-hidden="true">
        <Icon size={13} strokeWidth={1.8} />
      </span>
      <strong>{stationName(leg, side) || (boarding ? '출발 지점' : '도착 지점')}</strong>
      <span className="route-timeline-stop-kind">{kind}</span>
      {endpoint && (
        <span className={`route-timeline-end-tag ${endpoint === '도착' ? 'is-destination' : ''}`}>
          {endpoint}
        </span>
      )}
    </div>
  )
}

function BusOptions({ leg }: { leg: Leg }) {
  if (leg.mode !== 'bus' || leg.busRouteOptions === undefined) return null
  if (!leg.busRouteOptions.length)
    return <p className="route-timeline-direction">버스 노선 정보를 확인하지 못했어요.</p>
  if (leg.busRouteOptions.length === 1) {
    const headway = leg.busRouteOptions[0].headwayMin
    return headway ? <p className="route-timeline-direction">약 {headway}분 간격</p> : null
  }
  return (
    <section className="route-timeline-bus-options" aria-label="이용 가능한 버스">
      <details>
        <summary>이용 가능한 버스 {leg.busRouteOptions.length}개 노선</summary>
        <ul>
          {leg.busRouteOptions.map((option, index) => (
            <li key={`${option.routeId}-${index}`}>
              <span>{busOptionLabel(option)}</span>
              {!!option.headwayMin && <span>약 {option.headwayMin}분 간격</span>}
            </li>
          ))}
        </ul>
      </details>
    </section>
  )
}

export default function RouteTimeline({
  route,
  originName,
  destinationName,
  activeIndex,
  activeAction,
}: {
  route: Route
  originName?: string
  destinationName?: string
  /** Index in the original route.legs array. */
  activeIndex?: number
  activeAction?: { label: string; onConfirm: () => void }
}) {
  const timeline = useRef<HTMLOListElement>(null)
  const previousIndex = useRef(activeIndex)
  useEffect(() => {
    const changed = previousIndex.current !== undefined && previousIndex.current !== activeIndex
    previousIndex.current = activeIndex
    if (!changed || activeIndex === undefined) return
    const active = timeline.current?.querySelector<HTMLElement>('[aria-current="step"]')
    const body = timeline.current?.closest<HTMLElement>('.sheet-body')
    if (!active || !body) return
    const top =
      active.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - 12
    body.scrollTo?.({ top: Math.max(0, top), behavior: 'auto' })
  }, [activeIndex])
  const firstLeg = route.legs[0]
  const lastLeg = route.legs.at(-1)
  const origin = originName || (firstLeg && stationName(firstLeg, 'from')) || '출발'
  const destination = destinationName || (lastLeg && stationName(lastLeg, 'to')) || '도착'
  const startsAtStop =
    firstLeg &&
    (isTransitLeg(firstLeg) || firstLeg.mode === 'bike') &&
    origin === stationName(firstLeg, 'from')
  const endsAtStop =
    lastLeg &&
    (isTransitLeg(lastLeg) || lastLeg.mode === 'bike') &&
    destination === stationName(lastLeg, 'to')
  return (
    <ol ref={timeline} className="route-timeline" aria-label="경로 상세">
      {!startsAtStop && (
        <li className="route-timeline-endpoint route-timeline-origin">
          <span className="route-timeline-endpoint-marker">출발</span>
          <strong>{origin}</strong>
        </li>
      )}
      {route.legs.map((leg, index) => {
        const active = activeIndex === index
        const riding = isTransitLeg(leg) || leg.mode === 'bike'
        const color = isTransitLeg(leg)
          ? lineColor(leg) || '#4277d9'
          : leg.mode === 'bike'
            ? '#07866e'
            : undefined
        const copy = transitCopy(leg)
        const congestion = isTransitLeg(leg)
          ? segmentCongestionPresentation(segmentCongestionGradeForLeg(leg))
          : undefined
        return (
          <li
            key={`${index}-${leg.mode}`}
            className={`route-timeline-leg ${riding ? 'is-riding' : 'is-walk'}${active ? ' is-active' : ''}`}
            aria-current={active ? 'step' : undefined}
            data-leg-index={index}
            style={color ? ({ '--route-timeline-line': color } as CSSProperties) : undefined}
          >
            {riding ? (
              <div className="route-timeline-transit">
                <Stop
                  leg={leg}
                  side="from"
                  endpoint={index === 0 && startsAtStop ? '출발' : undefined}
                />
                <div className="route-timeline-service">
                  {active && activeAction?.label === '탑승했어요' && (
                    <button
                      className="secondary route-timeline-confirm"
                      onClick={activeAction.onConfirm}
                    >
                      {activeAction.label}
                    </button>
                  )}
                  <div className="route-timeline-service-row">
                    <span className="route-timeline-service-label">{copy.label}</span>
                    {congestion && (
                      <span
                        className="route-timeline-congestion"
                        style={{ color: congestion.color }}
                        aria-label={`구간 예상 혼잡도 ${congestion.label}`}
                      >
                        <span aria-hidden="true" />
                        {congestion.label}
                      </span>
                    )}
                  </div>
                  {copy.detail && <p className="route-timeline-direction">{copy.detail}</p>}
                  <BusOptions leg={leg} />
                  <SegmentMeta leg={leg} riding />
                </div>
                <Stop
                  leg={leg}
                  side="to"
                  endpoint={index === route.legs.length - 1 && endsAtStop ? '도착' : undefined}
                />
                {active && activeAction && activeAction.label !== '탑승했어요' && (
                  <button
                    className="secondary route-timeline-confirm"
                    onClick={activeAction.onConfirm}
                  >
                    {activeAction.label}
                  </button>
                )}
              </div>
            ) : (
              <div className="route-timeline-ordinary">
                <p className="route-timeline-walk-title">{leg.title}</p>
                {leg.note &&
                  leg.note !== leg.title &&
                  leg.note !== '이동 구간' &&
                  leg.note !== '도보' &&
                  leg.note !== transitionLabel(leg.transitionType) &&
                  !isEndpointPair(leg.note, leg) && (
                    <p className="route-timeline-direction">{leg.note}</p>
                  )}
                <SegmentMeta leg={leg} />
                {active && activeAction && (
                  <button
                    className="secondary route-timeline-confirm"
                    onClick={activeAction.onConfirm}
                  >
                    {activeAction.label}
                  </button>
                )}
              </div>
            )}
          </li>
        )
      })}
      {!endsAtStop && (
        <li className="route-timeline-endpoint route-timeline-destination">
          <span className="route-timeline-endpoint-marker">도착</span>
          <strong>{destination}</strong>
        </li>
      )}
    </ol>
  )
}
