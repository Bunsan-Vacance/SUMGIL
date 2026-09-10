import { ArrowLeft } from 'lucide-react'
import BottomSheet from '../components/BottomSheet'
import { modeIcons } from '../features/route/ModeIcon'
import { arrival, remaining, roundMinutes } from '../features/route/selectors'
import type { Route } from '../features/route/types'
import type { Navigate } from '../app/useNavigation'
import LegList from '../features/route/LegList'
interface Props {
  selected: Route
  step: number
  train: string | null
  destinationName: string
  go: Navigate
  onExit: () => void
}
export default function GuidePage({ selected, step, train, destinationName, go, onExit }: Props) {
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
      </div>
      <BottomSheet compact>
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
            <strong>{arrival(selected.minutes, selected.departedAt)}</strong>
            <small>도착</small>
            <b>{roundMinutes(remaining(selected, step))}분</b>
            <small>남음</small>
          </div>
        </div>
        <div className="next-leg">
          <small>다음 단계</small>
          <strong>{next?.title || `${destinationName} 도착`}</strong>
          {next && (
            <p>
              {next.note} · {roundMinutes(next.minutes)}분
            </p>
          )}
        </div>
        {train && (
          <p className="section-label">
            {train === 'unknown' ? '탑승 열차 미확인' : `${train} 출발 열차`}
          </p>
        )}
        <section className="route-legs" aria-label="전체 경로">
          <h3>전체 경로</h3>
          <LegList route={selected} />
        </section>
      </BottomSheet>
    </>
  )
}
