import { ArrowLeft } from 'lucide-react'
import BottomSheet from '../components/BottomSheet'
import { modeIcons } from '../features/route/ModeIcon'
import { remaining, roundMinutes, routeArrival } from '../features/route/selectors'
import type { Route } from '../features/route/types'
import type { TrainArrival } from '../api/guidance'
import type { Navigate } from '../app/useNavigation'
import LegList from '../features/route/LegList'
interface Props {
  selected: Route
  step: number
  train: string | null
  selectedArrival: TrainArrival | null
  destinationName: string
  go: Navigate
  onExit: () => void
  onPrevious: () => void
  onNext: () => void
  onTrain: () => void
  onReplan: () => void
  replanDisabled: boolean
}

function formatArrival(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(value))
}
export default function GuidePage({
  selected,
  step,
  train,
  selectedArrival,
  destinationName,
  go,
  onExit,
  onPrevious,
  onNext,
  onTrain,
  onReplan,
  replanDisabled,
}: Props) {
  const currentLeg = selected.legs[Math.min(step, selected.legs.length - 1)]
  const CurrentIcon = modeIcons[currentLeg.mode]
  const next = selected.legs[step + 1]
  return (
    <>
      <div className="guide-top">
        <div className="row">
          <button
            className="icon-button"
            aria-label="경로 결과로 돌아가기"
            onClick={() => go('results')}
          >
            <ArrowLeft />
          </button>
          <strong>길안내</strong>
          {selected.source === 'MOCK' && <small className="guide-source">샘플 경로</small>}
        </div>
        <div className="maneuver">
          <span className="leg-icon">
            <CurrentIcon size={22} />
          </span>
          <div>
            <strong>{currentLeg.title}</strong>
            <p>
              {currentLeg.note} · {roundMinutes(currentLeg.minutes)}분
            </p>
          </div>
        </div>
        <p className="manual-guidance-note">필요한 단계에서 직접 다음 안내를 눌러 이동해요.</p>
      </div>
      <BottomSheet
        compact
        footer={
          <>
            <button className="secondary" onClick={onPrevious} disabled={step === 0}>
              이전 단계
            </button>
            <button className="primary" onClick={onNext}>
              {step === selected.legs.length - 1 ? '도착' : '다음 단계'}
            </button>
          </>
        }
      >
        <header className="row between">
          <h2>
            길안내{' '}
            <small className="muted">
              {step + 1}/{selected.legs.length}
            </small>
          </h2>
          <button className="secondary" onClick={onExit}>
            안내 종료
          </button>
        </header>
        <div className="eta">
          <div>
            <small>도착 예정</small>
            <strong>{destinationName}</strong>
          </div>
          <div>
            <strong>{routeArrival(selected.minutes, selected.departedAt)}</strong>
            <small>도착</small>
            <b>{roundMinutes(remaining(selected, step))}분</b>
            <small>남음</small>
          </div>
        </div>
        <div className="guidance-secondary-actions">
          {currentLeg.mode === 'subway' && (
            <button className="secondary" onClick={onTrain}>
              탑승 확인
            </button>
          )}
          <button
            className="secondary"
            onClick={onReplan}
            disabled={replanDisabled}
            title={replanDisabled ? '하차 후 다음 단계에서 다시 찾을 수 있어요.' : undefined}
          >
            다른 경로 찾기
          </button>
        </div>
        {replanDisabled && (
          <p className="dialog-state">하차 후 다음 단계에서 다시 찾을 수 있어요.</p>
        )}
        <div className="next-leg">
          <small>다음 단계</small>
          <strong>{next?.title || `${destinationName} 도착`}</strong>
          {next && (
            <p>
              {next.note} · {roundMinutes(next.minutes)}분
            </p>
          )}
        </div>
        {selectedArrival && (
          <p className="section-label">
            {formatArrival(selectedArrival.arrivalTime)} · {selectedArrival.direction} 도착 예정
          </p>
        )}
        {train === 'unknown' && <p className="section-label">탑승 열차 미확인</p>}
        <section className="route-legs" aria-label="전체 경로">
          <h3>전체 경로</h3>
          <LegList route={selected} activeIndex={step} />
        </section>
      </BottomSheet>
    </>
  )
}
