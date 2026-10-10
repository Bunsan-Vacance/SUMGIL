import { ArrowLeft, Navigation, Radio, Share2 } from 'lucide-react'
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
  confirmationLabel,
  distanceToEndpoint,
  guidanceEndpoint,
  type GuidancePosition,
} from '../features/guidance/locationProgress'
import {
  busLegOptions,
  busRouteOptions,
  formatBusLabel,
  groupRoutes,
} from '../features/route/routeGrouping'
import './DetailPage.css'

export interface RouteGuidanceControls {
  step: number
  boarded?: boolean
  position?: GuidancePosition | null
  onConfirm?: () => void
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
  onShare?: () => void
}
const locationMessages: Record<GuidanceLocationStatus, string> = {
  idle: '위치 안내를 준비하고 있어요.',
  waiting: '현재 위치를 확인하고 있어요.',
  tracking: '위치를 확인하며 구간을 자동으로 안내해요.',
  denied: '위치 권한을 허용하면 자동으로 안내해요.',
  'no-position': '위치가 잡히지 않으면 아래에서 현재 구간을 조정해 주세요.',
  unsupported: '위치 안내를 사용할 수 없어요. 현재 구간을 직접 선택해 주세요.',
  inaccurate: '위치 오차가 커요. 정확한 위치가 잡히면 자동 안내를 이어갈게요.',
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
  onShare,
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
  const confirmLabel = confirmationLabel(currentLeg, guidance?.boarded)
  const distance = guidance?.position
    ? distanceToEndpoint(guidance.position, currentLeg)
    : undefined
  const progressMessage = confirmLabel
    ? currentLeg?.mode === 'subway' && guidance?.boarded
      ? `${currentLeg.to?.name || '도착역'}에서 하차 후 확인해 주세요.`
      : confirmLabel === '탑승했어요'
        ? '승차 후 현재 구간에서 탑승을 확인해 주세요.'
        : confirmLabel === '하차했어요'
          ? '하차 후 현재 구간에서 확인해 주세요.'
          : confirmLabel === '대여했어요'
            ? '자전거를 대여한 뒤 확인해 주세요.'
            : '자전거를 반납한 뒤 확인해 주세요.'
    : currentLeg && !guidanceEndpoint(currentLeg)
      ? '이 구간은 도착 위치 정보가 없어 직접 다음 구간으로 넘겨 주세요.'
      : guidance?.locationStatus === 'tracking' && distance !== undefined
        ? `${currentLeg?.to?.name || '다음 지점'}${distance <= 50 ? ' 근처예요.' : `까지 약 ${distance < 1000 ? `${Math.round(distance / 10) * 10}m` : `${(distance / 1000).toFixed(1)}km`}`}`
        : guidance
          ? locationMessages[guidance.locationStatus]
          : ''
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
            <div className="route-detail-time-group">
              <h2>{roundMinutes(selected.minutes)}분</h2>
              <p className="route-detail-times">
                {departure ? `${departure} – ${arrival}` : `${arrival} 도착 예상`}
                <span>환승 {selected.transfers}회</span>
              </p>
            </div>
            {isCongestionPredictionDate(selected.departedAt) && (
              <div
                className={`route-detail-congestion${presentation ? '' : ' is-unavailable'}`}
                aria-label={`전체 경로 혼잡도 예상 ${presentation?.label ?? '정보 없음'}`}
              >
                <strong style={{ color: presentation?.color }}>
                  {presentation?.label ?? '정보 없음'}
                </strong>
                <span>혼잡도 예상</span>
              </div>
            )}
            {!guidance && onShare && (
              <button
                type="button"
                className="icon-button route-detail-share"
                aria-label="경로 공유"
                onClick={onShare}
              >
                <Share2 size={18} />
              </button>
            )}
          </div>
          <RouteModeStrip legs={selected.legs} />
          {(selected.walk !== undefined || selected.source === 'MOCK') && (
            <div className="route-detail-meta stats">
              {selected.walk !== undefined && <span>도보 {selected.walk}m</span>}
              {selected.source === 'MOCK' && <small>샘플 경로</small>}
            </div>
          )}
        </header>
        {guidance && (
          <section className="route-detail-guidance" aria-label="현재 구간 안내">
            <span className="route-detail-live">
              <Radio size={14} />
              안내 중
            </span>
            <p role="status" aria-live="polite">
              <strong>{currentLeg?.title}</strong>
              <span>{progressMessage}</span>
            </p>
            {!confirmLabel &&
              ['denied', 'no-position', 'unsupported'].includes(guidance.locationStatus) && (
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
                {currentLeg?.mode === 'subway' && !currentLeg.transitionType && (
                  <button className="secondary" onClick={guidance.onTrain}>
                    탑승 열차 선택
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
            activeAction={
              guidance?.onConfirm && confirmLabel
                ? { label: confirmLabel, onConfirm: guidance.onConfirm }
                : undefined
            }
          />
        </section>
      </BottomSheet>
    </>
  )
}
