import { Check, Star } from 'lucide-react'
export default function ArrivalPage({
  destinationName,
  onHome,
  canSave,
  saved,
  onSaveRoute,
}: {
  destinationName: string
  onHome: () => void
  canSave: boolean
  saved: boolean
  onSaveRoute: () => void
}) {
  return (
    <section className="arrival">
      <span className="arrival-icon">
        <Check size={40} />
      </span>
      <h2>도착했어요</h2>
      <p>{destinationName}</p>
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
