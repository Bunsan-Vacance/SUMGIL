import { Check } from 'lucide-react'
import { arrival, roundMinutes } from './selectors'
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
  const facts = [
    route.walk === undefined ? null : `도보 ${route.walk}m`,
    `환승 ${route.transfers ? `${route.transfers}회` : '없음'}`,
    route.congestionPercent === undefined ? null : `혼잡도 ${route.congestionPercent}%`,
  ].filter((fact): fact is string => fact !== null)
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
          <b>{roundMinutes(route.minutes)}</b>분
        </span>
        <small>{arrival(route.minutes, route.departedAt)} 도착</small>
      </span>
      {route.line && <span className="route-lines">{route.line}</span>}
      <span className="route-facts">
        {facts.map((fact, index) => (
          <span key={fact}>
            {index > 0 && <i />}
            {fact}
          </span>
        ))}
      </span>
    </button>
  )
}
