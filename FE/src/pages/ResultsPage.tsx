import { useState } from 'react'
import { ArrowLeftRight, ChevronDown, Gauge, SlidersHorizontal, UsersRound, X } from 'lucide-react'
import DepartureTimeDialog from '../features/route/DepartureTimeDialog'
import RouteCard from '../features/route/RouteCard'
import type { Mode, Place, Priority, Route } from '../features/route/types'
import type { TripState } from '../features/route/tripReducer'
import type { Navigate } from '../app/useNavigation'
import { clockTime } from '../features/route/selectors'
import { isBackendConfigured } from '../api/repositories'

interface Props {
  origin: Place
  destinationName: string
  visible: Route[]
  selectedId: string | null
  setSelectedId: (id: string) => void
  status: TripState['status']
  retry: () => void
  error: string
  enabled: Mode[]
  priority: Priority
  setPriority: (value: Priority) => void
  openFilter: () => void
  openSearch: (target: 'origin' | 'destination') => void
  onBackToInput: () => void
  go: Navigate
  startGuide?: () => void
  canSwap: boolean
  swapPlaces: () => void
  isLiveApi?: boolean
  departureTime?: string
  onDepartureTimeChange?: (time: string) => void
}

export default function ResultsPage({
  origin,
  destinationName,
  visible,
  setSelectedId,
  status,
  retry,
  error,
  enabled,
  priority,
  setPriority,
  openFilter,
  openSearch,
  onBackToInput,
  go,
  canSwap,
  swapPlaces,
  isLiveApi,
  departureTime,
  onDepartureTimeChange,
}: Props) {
  const [choosingTime, setChoosingTime] = useState(false)
  const hasCongestion = visible.some((route) => route.congestionPercent !== undefined)
  const liveApi = isLiveApi ?? isBackendConfigured
  const departure = departureTime || clockTime(visible[0]?.departedAt)

  return (
    <section className="results-screen" aria-label="경로 검색 결과">
      <header className="results-top">
        <div className="results-trip-card">
          <button
            type="button"
            className="results-swap"
            aria-label="출발지와 도착지 교환"
            disabled={!canSwap}
            onClick={swapPlaces}
          >
            <ArrowLeftRight size={22} />
          </button>
          <div className="results-trip-fields">
            <button
              type="button"
              className="results-trip-field"
              aria-label="출발지 수정"
              onClick={() => openSearch('origin')}
            >
              <i className="dot start" />
              <span>{origin.name}</span>
            </button>
            <button
              type="button"
              className="results-trip-field"
              aria-label="도착지 수정"
              onClick={() => openSearch('destination')}
            >
              <i className="dot end" />
              <span>{destinationName}</span>
            </button>
          </div>
          <button
            type="button"
            className="results-close"
            aria-label="경로 입력으로 돌아가기"
            onClick={onBackToInput}
          >
            <X size={27} />
          </button>
        </div>
        <div className="results-priority" role="group" aria-label="경로 우선순위">
          <button
            type="button"
            aria-pressed={priority === 'fast'}
            onClick={() => setPriority('fast')}
          >
            <Gauge size={20} aria-hidden="true" />
            <span>속도</span>
          </button>
          <button
            type="button"
            aria-pressed={priority === 'calm'}
            aria-label="혼잡"
            disabled={!hasCongestion}
            onClick={() => setPriority('calm')}
          >
            <UsersRound size={20} aria-hidden="true" />
            <span>혼잡</span>
            {!hasCongestion && <small>준비중입니다</small>}
          </button>
        </div>
      </header>

      <div className="results-scroll">
        <div className="results-sort-row">
          <button
            type="button"
            className="results-departure"
            aria-label="출발 시간 선택"
            onClick={() => setChoosingTime(true)}
          >
            {departure ? (
              <>
                오늘 <b>{departure}</b> 출발
              </>
            ) : (
              '출발 시간 선택'
            )}
            <ChevronDown size={14} aria-hidden="true" />
          </button>
          <button type="button" className="results-filter" onClick={openFilter}>
            <SlidersHorizontal size={14} aria-hidden="true" />
            이동수단
            <span className="sr-only">{enabled.length}/4 선택됨</span>
          </button>
          <span className="results-sort" aria-label="정렬 기준">
            {priority === 'calm' ? '혼잡도 낮은 순' : '빠른 순'}
          </span>
        </div>

        {status === 'loading' ? (
          <div className="empty results-state" role="status">
            <span className="spinner" />
            <h2>경로를 찾고 있어요</h2>
          </div>
        ) : status === 'error' ? (
          <div className="empty results-state" role="alert">
            <h2>{error || '경로를 불러오지 못했어요.'}</h2>
            <button className="primary" onClick={retry}>
              다시 시도
            </button>
          </div>
        ) : (
          <>
            {!liveApi && <p className="results-sample">시안 · 예시 데이터</p>}
            <div className="route-list">
              {visible.map((route) => (
                <RouteCard
                  key={route.id}
                  route={route}
                  onDetail={() => {
                    setSelectedId(route.id)
                    go('detail')
                  }}
                />
              ))}
            </div>
            {!visible.length && (
              <div className="empty">
                <h3>해당 수단으로는 경로가 없어요</h3>
                <button className="secondary" onClick={openFilter}>
                  조건 변경
                </button>
              </div>
            )}
          </>
        )}
      </div>
      {choosingTime && (
        <DepartureTimeDialog
          initialValue={departure || clockTime(new Date().toISOString()) || '00:00'}
          onClose={() => setChoosingTime(false)}
          onApply={(time) => {
            onDepartureTimeChange?.(time)
            setChoosingTime(false)
          }}
        />
      )}
    </section>
  )
}
