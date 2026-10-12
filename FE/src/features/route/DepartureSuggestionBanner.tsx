import { ChevronRight, Clock } from 'lucide-react'
import { suggestionView } from './departureSuggestion'
import type { RouteSuggestion, SuggestionKind } from './useDepartureAlternatives'

interface Props {
  suggestions: RouteSuggestion[]
  onApply: (clock: string) => void
}

const KINDS: Record<SuggestionKind, { badge: string; aria: string; tone: 'fast' | 'calm' }> = {
  fast: { badge: '가장 빠른', aria: '가장 빠른 경로', tone: 'fast' },
  calm: { badge: '덜 붐비는', aria: '덜 붐비는 경로', tone: 'calm' },
  both: { badge: '추천', aria: '추천 경로', tone: 'fast' },
}

/** 출발 시각 줄 아래에 놓는 덜 붐비는 출발 시각 제안. 행을 누르면 그 시각으로 다시 찾는다. */
export default function DepartureSuggestionBanner({ suggestions, onApply }: Props) {
  if (suggestions.length === 0) return null
  return (
    <section className="results-suggestions" aria-label="덜 붐비는 출발 시각">
      <span className="results-suggestions-head">
        <Clock size={20} aria-hidden="true" />
        조금 늦게 출발하면 덜 붐벼요 <small>· 예측 기준</small>
      </span>
      {suggestions.map(({ kind, routeId, suggestion }) => {
        const view = suggestionView(suggestion)
        const meta = KINDS[kind]
        return (
          <button
            key={routeId}
            type="button"
            className="results-suggestion-row"
            aria-label={view.ariaLabel(meta.aria)}
            onClick={() => onApply(suggestion.clock)}
          >
            <span className={`route-recommendation-badge ${meta.tone}`}>{meta.badge}</span>
            <span className="results-suggestion-text">
              <b>{suggestion.clock}</b> 출발 ·{' '}
              <span style={{ color: view.fromColor }}>{view.fromLabel}</span>
              {' → '}
              <span style={{ color: view.toColor }}>{view.toLabel}</span> · {view.arrival}
            </span>
            <span className="results-suggestion-action">
              바꾸기
              <ChevronRight size={18} aria-hidden="true" />
            </span>
          </button>
        )
      })}
    </section>
  )
}
