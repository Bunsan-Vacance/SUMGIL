import { Check } from 'lucide-react'
export default function ArrivalPage({
  destinationName,
  onHome,
}: {
  destinationName: string
  onHome: () => void
}) {
  return (
    <section className="arrival">
      <span className="arrival-icon">
        <Check size={40} />
      </span>
      <h2>도착했어요</h2>
      <p>{destinationName}</p>
      <button className="primary" onClick={onHome}>
        홈으로 돌아가기
      </button>
    </section>
  )
}
