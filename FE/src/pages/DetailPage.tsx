import { ArrowLeft, Navigation } from 'lucide-react'
import BottomSheet from '../components/BottomSheet'
import LegList from '../features/route/LegList'
import BikePrediction from '../features/route/BikePrediction'
import {
  congestionPredictionFor,
  formatCongestionPercent,
  isCongestionPredictionDate,
  routeArrival,
  roundMinutes,
} from '../features/route/selectors'
import type { Place, Route } from '../features/route/types'
import type { Navigate } from '../app/useNavigation'
import {
  busLegOptions,
  busOptionLabel,
  busRouteOptions,
  formatBusLabel,
  groupRoutes,
} from '../features/route/routeGrouping'
interface Props {
  origin: Place
  destinationName: string
  selected: Route
  alternatives: Route[]
  setSelectedId: (id: string) => void
  go: Navigate
  startGuide: () => void
}
export default function DetailPage({
  origin,
  destinationName,
  selected,
  alternatives,
  setSelectedId,
  go,
  startGuide,
}: Props) {
  const selectedGroup = groupRoutes(alternatives).find((group) =>
    group.variants.some((route) => route.id === selected.id),
  )
  const inlineBusSegments = busLegOptions(selected)
  const legacyBusOptions = selectedGroup ? busRouteOptions(selectedGroup.variants) : []
  const predictionDate = isCongestionPredictionDate(selected.departedAt)
  const prediction = congestionPredictionFor(selected)
  const formattedPercent = prediction
    ? formatCongestionPercent(prediction.congestionPercent)
    : undefined
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
        </div>
        {selected.source === 'MOCK' && <small className="detail-source">샘플 경로</small>}
        <div className="stats">
          {selected.totalDistanceMeters !== undefined && (
            <div>
              <strong>{Math.round(selected.totalDistanceMeters).toLocaleString('ko-KR')}m</strong>
              <small>전체 거리</small>
            </div>
          )}
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
          {predictionDate && (
            <div>
              <strong>{prediction ? `${formattedPercent}%` : '정보 없음'}</strong>
              <small>혼잡도 예상</small>
            </div>
          )}
        </div>
        <BikePrediction route={selected} />
        {inlineBusSegments.length > 0 && (
          <section className="bus-options" aria-label="이용 가능한 버스">
            <h3>이용 가능한 버스</h3>
            {inlineBusSegments.map(({ leg, index, options }) => (
              <div className="bus-options-segment" key={index}>
                <h4>
                  {leg.from?.name || '출발 정류장'} → {leg.to?.name || '도착 정류장'}
                </h4>
                {options.length ? (
                  <details className="bus-options-details" open={options.length === 1}>
                    <summary>이용 가능한 버스 {options.length}개 노선</summary>
                    <div className="bus-options-list">
                      {options.map((option) => (
                        <div className="bus-option" key={option.routeId}>
                          <strong>{busOptionLabel(option)}</strong>
                          <span>
                            {option.headwayMin
                              ? `약 ${option.headwayMin}분 간격`
                              : '배차 정보 없음'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : (
                  <p className="bus-options-empty">버스 노선 정보를 확인하지 못했어요.</p>
                )}
              </div>
            ))}
          </section>
        )}
        {inlineBusSegments.length === 0 && legacyBusOptions.length > 1 && (
          <section className="bus-options" aria-label="버스 선택">
            <h3>버스 선택</h3>
            <div className="bus-options-list">
              {legacyBusOptions.map(({ route, labels }) => (
                <button
                  type="button"
                  key={route.id}
                  className={route.id === selected.id ? 'is-selected' : undefined}
                  aria-pressed={route.id === selected.id}
                  onClick={() => setSelectedId(route.id)}
                >
                  <strong>{labels.map(formatBusLabel).join(' · ')}</strong>
                  <span>{roundMinutes(route.minutes)}분</span>
                </button>
              ))}
            </div>
          </section>
        )}
        <section className="route-legs" aria-label="구간별 이동 안내">
          <h3>구간별 이동 안내</h3>
          <LegList route={selected} />
        </section>
      </BottomSheet>
    </>
  )
}
