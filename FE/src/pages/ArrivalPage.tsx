import { Check, Star } from 'lucide-react'
import type { CSSProperties } from 'react'
import type { FeedbackGrade } from '../api/congestionFeedback'
import type { FeedbackTarget } from '../features/feedback/congestionFeedback'
import { feedbackCardView, feedbackOptionView } from '../features/feedback/feedbackCard'

function FeedbackCard({
  target,
  grade,
  onSelect,
}: {
  target: FeedbackTarget
  grade: FeedbackGrade | null
  onSelect: (grade: FeedbackGrade) => void
}) {
  if (grade) {
    const sent = feedbackOptionView(grade)
    return (
      <section
        className="arrival-feedback sent"
        role="status"
        style={{ '--feedback-color': sent.color } as CSSProperties}
      >
        <span className="arrival-feedback-sent-icon">
          <i />
        </span>
        <span className="arrival-feedback-sent-text">
          <strong>&apos;{sent.label}&apos;으로 알려주셨어요</strong>
          <small>다음 혼잡도 예측에 참고할게요</small>
        </span>
      </section>
    )
  }
  const view = feedbackCardView(target)
  return (
    <section className="arrival-feedback">
      <div className="arrival-feedback-head">
        <strong>{view.title}</strong>
        <span>
          {view.line && (
            <i
              className="arrival-feedback-line"
              style={{ background: view.line.background, color: view.line.color }}
            >
              {view.line.label}
            </i>
          )}
          {view.subtitle}
        </span>
      </div>
      <div className="arrival-feedback-options" role="group" aria-label="실제 혼잡도">
        {view.options.map((option) => (
          <button
            key={option.grade}
            type="button"
            style={{ '--feedback-color': option.color } as CSSProperties}
            onClick={() => onSelect(option.grade)}
          >
            <i />
            <strong>{option.label}</strong>
            <small>{option.hint}</small>
          </button>
        ))}
      </div>
    </section>
  )
}

export default function ArrivalPage({
  destinationName,
  onHome,
  canSave,
  saved,
  onSaveRoute,
  feedbackTarget,
  feedbackGrade = null,
  onFeedback,
}: {
  destinationName: string
  onHome: () => void
  canSave: boolean
  saved: boolean
  onSaveRoute: () => void
  feedbackTarget?: FeedbackTarget | null
  feedbackGrade?: FeedbackGrade | null
  onFeedback?: (grade: FeedbackGrade) => void
}) {
  return (
    <section className="arrival">
      <span className="arrival-icon">
        <Check size={40} />
      </span>
      <h2>도착했어요</h2>
      <p>{destinationName}</p>
      {feedbackTarget && onFeedback && (
        <FeedbackCard target={feedbackTarget} grade={feedbackGrade} onSelect={onFeedback} />
      )}
      {canSave && (
        <button
          type="button"
          className="secondary"
          aria-pressed={saved}
          disabled={saved}
          onClick={onSaveRoute}
        >
          <Star size={17} fill={saved ? 'currentColor' : 'none'} />
          {saved ? '저장됨' : '이 경로 저장'}
        </button>
      )}
      <button className="primary" onClick={onHome}>
        홈으로 돌아가기
      </button>
    </section>
  )
}
