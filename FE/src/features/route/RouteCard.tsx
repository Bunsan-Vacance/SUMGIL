import { Check } from 'lucide-react'
import { arrival } from './selectors'
import type { Route } from './types'

export default function RouteCard({
  route,
  selected,
  onSelect,
}: {
  route: Route
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      className={`route-card ${selected ? 'selected' : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="route-heading">
        <span
          className={route.id === 'calm' ? 'calm-text' : route.id === 'fast' ? 'fast-text' : ''}
        >
          {route.label}
        </span>
        {selected && (
          <small className="selected-label">
            <Check size={11} />
            선택됨
          </small>
        )}
      </span>
      <span className="route-time">
        <span>
          <b>{route.minutes}</b>분
        </span>
        <small>{arrival(route.minutes)} 도착</small>
      </span>
      <span className="route-lines">{route.line}</span>
      <span className="route-facts">
        도보 {route.walk}m <i /> 환승 {route.transfers ? `${route.transfers}회` : '없음'} <i />{' '}
        혼잡도 {route.congestionPercent}%
      </span>
    </button>
  )
}
