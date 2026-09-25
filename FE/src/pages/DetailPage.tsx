import { ArrowLeft, Navigation, Radio } from 'lucide-react'
import BottomSheet from '../components/BottomSheet'
import RouteTimeline from '../features/route/RouteTimeline'
import BikePrediction from '../features/route/BikePrediction'
import RouteModeStrip from '../features/route/RouteModeStrip'
import {
  clockTime,
  congestionPredictionFor,
  congestionPredictionPresentation,
  isCongestionPredictionDate,
  remaining,
  routeArrival,
  roundMinutes,
} from '../features/route/selectors'
import type { Route } from '../features/route/types'
import type { Navigate } from '../app/useNavigation'
import type { GuidanceLocationStatus } from '../features/guidance/guidanceReducer'
import {
  busLegOptions,
  busRouteOptions,
  formatBusLabel,
  groupRoutes,
} from '../features/route/routeGrouping'
import './DetailPage.css'

export interface RouteGuidanceControls {
  step: number
  locationStatus: GuidanceLocationStatus
  onExit: () => void
  onPrevious: () => void
  onNext: () => void
  onTrain: () => void
  onReplan: () => void
  replanDisabled: boolean
  onRetryLocation: () => void
  onStepChange: (step: number) => void
}
interface Props {
  selected: Route
  alternatives: Route[]
  setSelectedId: (id: string) => void
  go: Navigate
  startGuide: () => void
  originName?: string
  destinationName?: string
  guidance?: RouteGuidanceControls
}
const locationMessages: Record<GuidanceLocationStatus, string> = {
  idle: '위치 안내를 준비하고 있어요.',
  waiting: '현재 위치를 확인하고 있어요.',
  tracking: '위치를 확인하며 구간을 자동으로 안내해요.',
  denied: '위치 권한을 허용하면 자동으로 안내해요.',
  'no-position': '위치가 잡히지 않으면 아래에서 현재 구간을 조정해 주세요.',
  unsupported: '위치 안내를 사용할 수 없어요. 현재 구간을 직접 선택해 주세요.',
}
export default function DetailPage({
  selected,
  alternatives,
  setSelectedId,
  go,
  startGuide,
  originName,
  destinationName,
  guidance,
}: Props) {
  const selectedGroup = groupRoutes(alternatives).find((group) =>
    group.variants.some((route) => route.id === selected.id),
  )
  const legacyBusOptions = selectedGroup ? busRouteOptions(selectedGroup.variants) : []
  const prediction = congestionPredictionFor(selected)
  const presentation = congestionPredictionPresentation(prediction, selected.legs)
  const departure = clockTime(selected.departedAt)
  const arrival = routeArrival(selected.minutes, selected.departedAt)
  const currentLeg = guidance ? selected.legs[guidance.step] : undefined
  const minutes = guidance ? remaining(selected, guidance.step) : selected.minutes
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
        className="route-detail-sheet"
        footer={
          <div className="route-detail-footer">
            <div className="route-detail-eta">
              <strong>
                {roundMinutes(minutes)}분{guidance ? ' 남음' : ''}
              </strong>
              <span>{arrival} 도착 예정</span>
            </div>
            {guidance ? (
              <button className="secondary" onClick={guidance.onExit}>
                안내 종료
              </button>
            ) : (
              <button className="primary" onClick={startGuide}>
                <Navigation size={17} />
                안내 시작
              </button>
            )}
          </div>
        }
      >
        <header className="route-detail-summary">
          <div className="route-detail-summary-top">
            <h2>
              {roundMinutes(selected.minutes)}
              <small>분</small>
            </h2>
            {guidance && (
              <span className="route-detail-live">
                <Radio size={14} />
                안내 중
              </span>
            )}
          </div>
          <p className="route-detail-times">
            {departure ? `${departure} – ${arrival}` : `${arrival} 도착 예상`}
            <span>환승 {selected.transfers}회</span>
          </p>
          <RouteModeStrip legs={selected.legs} />
          <div className="route-detail-meta stats">
            {selected.walk !== undefined && <span>도보 {selected.walk}m</span>}
            {isCongestionPredictionDate(selected.departedAt) && (
              <span>
                <span>혼잡도 예상</span>{' '}
                <strong style={{ color: presentation?.color }}>
                  {presentation?.label ?? '정보 없음'}
                </strong>
              </span>
            )}
            {selected.source === 'MOCK' && <small>샘플 경로</small>}
          </div>
        </header>
        {guidance && (
          <section className="route-detail-guidance" aria-label="현재 구간 안내">
            <p role="status" aria-live="polite">
              <strong>{currentLeg?.title}</strong>
              <span>{locationMessages[guidance.locationStatus]}</span>
            </p>
            {['denied', 'no-position', 'unsupported'].includes(guidance.locationStatus) && (
              <button className="text-button" onClick={guidance.onRetryLocation}>
                위치 다시 확인
              </button>
            )}
            <details className="route-detail-adjust">
              <summary>안내 조정</summary>
              <label>
                현재 구간
                <select
                  aria-label="현재 안내 단계"
                  value={guidance.step}
                  onChange={(event) => guidance.onStepChange(Number(event.target.value))}
                >
                  {selected.legs.map((leg, index) => (
                    <option key={index} value={index}>
                      {index + 1}. {leg.title}
                    </option>
                  ))}
                </select>
              </label>
              <div className="route-detail-actions">
                <button
                  className="secondary"
                  disabled={guidance.step === 0}
                  onClick={guidance.onPrevious}
                >
                  이전 구간
                </button>
                <button className="secondary" onClick={guidance.onNext}>
                  {guidance.step === selected.legs.length - 1 ? '도착 확인' : '다음 구간'}
                </button>
              </div>
              <div className="route-detail-actions">
                {currentLeg?.mode === 'subway' && (
                  <button className="secondary" onClick={guidance.onTrain}>
                    탑승 확인
                  </button>
                )}
                <button
                  className="secondary"
                  onClick={guidance.onReplan}
                  disabled={guidance.replanDisabled}
                >
                  다른 경로 찾기
                </button>
              </div>
              {guidance.replanDisabled && <p>하차 후 다음 구간에서 다시 찾을 수 있어요.</p>}
            </details>
          </section>
        )}
        <BikePrediction route={selected} />
        {!guidance && busLegOptions(selected).length === 0 && legacyBusOptions.length > 1 && (
          <section className="bus-options" aria-label="버스 선택">
            <h3>버스 선택</h3>
            <div className="bus-options-list">
              {legacyBusOptions.map(({ route, labels }) => (
                <button
                  type="button"
                  key={route.id}
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
        <section aria-label="구간별 이동 안내" className="route-detail-journey">
          <h3 className="sr-only">구간별 이동 안내</h3>
          <RouteTimeline
            route={selected}
            originName={originName}
            destinationName={destinationName}
            activeIndex={guidance?.step}
          />
        </section>
      </BottomSheet>
    </>
  )
}
