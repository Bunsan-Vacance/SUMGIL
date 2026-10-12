import { ChevronRight, Clock } from 'lucide-react'
import { suggestionView, type DepartureSuggestion } from './departureSuggestion'

interface Props {
  suggestion: DepartureSuggestion
  onApply: (clock: string) => void
}

/** 가장 빠른 경로 아래에 놓는 덜 붐비는 출발 시각 제안. 누르면 그 시각으로 다시 찾는다. */
export default function DepartureSuggestionChip({ suggestion, onApply }: Props) {
  const view = suggestionView(suggestion)
  return (
    <button
      type="button"
      className="results-suggestion"
      aria-label={view.ariaLabel}
      onClick={() => onApply(suggestion.clock)}
    >
      <Clock size={18} aria-hidden="true" />
      <span className="results-suggestion-text">
        <strong>
          {view.title} <span style={{ color: view.fromColor }}>{view.fromLabel}</span>
          {' → '}
          <span style={{ color: view.toColor }}>{view.toLabel}</span>
        </strong>
        <small>{view.detail}</small>
      </span>
      <span className="results-suggestion-action">
        바꾸기
        <ChevronRight size={16} aria-hidden="true" />
      </span>
    </button>
  )
}
