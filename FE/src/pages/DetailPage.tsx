import { ArrowLeft, Navigation } from 'lucide-react'
import BottomSheet from '../components/BottomSheet'
import LegList from '../features/route/LegList'
import { routeArrival, roundMinutes } from '../features/route/selectors'
import type { Place, Route } from '../features/route/types'
import type { Navigate } from '../app/useNavigation'
interface Props {
  origin: Place
  destinationName: string
  selected: Route
  go: Navigate
  startGuide: () => void
}
export default function DetailPage({ origin, destinationName, selected, go, startGuide }: Props) {
  return (
    <>
      <button
        className="icon-button map-back"
        aria-label="경로 결과로 돌아가기"
        onClick={() => go('results')}
      >
        <ArrowLeft />
      </button>
      <BottomSheet
        key="detail"
        footer={
          <button className="primary" onClick={startGuide}>
            길안내 시작
            <Navigation size={17} />
          </button>
        }
      >
        <p className="section-label">
          {origin.name} → {destinationName}
        </p>
        <div className="detail-title">
          <h2>
            {roundMinutes(selected.minutes)}
            <small>분</small>
          </h2>
          <span>{routeArrival(selected.minutes, selected.departedAt)} 도착 예상</span>
          <b className={selected.id === 'calm' ? 'calm-text' : 'fast-text'}>{selected.label}</b>
        </div>
        <div className="stats">
          <div>
            <strong>{selected.transfers}회</strong>
            <small>환승</small>
          </div>
          {selected.walk !== undefined && (
            <div>
              <strong>{selected.walk}m</strong>
              <small>도보</small>
            </div>
          )}
          {selected.congestionPercent !== undefined && (
            <div>
              <strong>{selected.congestionPercent}%</strong>
              <small>혼잡도 예상</small>
            </div>
          )}
        </div>
        <section className="route-legs" aria-label="구간별 이동 안내">
          <h3>구간별 이동 안내</h3>
          <LegList route={selected} />
        </section>
      </BottomSheet>
    </>
  )
}
