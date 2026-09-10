import { ArrowLeft, ArrowLeftRight, Navigation, SlidersHorizontal } from 'lucide-react'
import BottomSheet from '../components/BottomSheet'
import RouteCard from '../features/route/RouteCard'
import type { Mode, Place, Priority, Route } from '../features/route/types'
import type { TripState } from '../features/route/tripReducer'
import type { Navigate } from '../app/useNavigation'
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
  startGuide: () => void
  canSwap: boolean
  swapPlaces: () => void
  isLiveApi?: boolean
}
export default function ResultsPage({
  origin,
  destinationName,
  visible,
  selectedId,
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
  startGuide,
  canSwap,
  swapPlaces,
  isLiveApi,
}: Props) {
  const hasCongestion = visible.some((route) => route.congestionPercent !== undefined)
  const liveApi = isLiveApi ?? isBackendConfigured
  return (
    <>
      <div className="trip-summary">
        <button
          type="button"
          className="icon-button summary-back"
          aria-label="경로 입력으로 돌아가기"
          onClick={onBackToInput}
        >
          <ArrowLeft size={17} />
        </button>
        <div>
          <button
            type="button"
            className="trip-summary-field"
            aria-label="출발지 수정"
            onClick={() => openSearch('origin')}
          >
            <i className="dot start" />
            출발 <b>{origin.name}</b>
          </button>
          <button
            type="button"
            className="trip-summary-field"
            aria-label="도착지 수정"
            onClick={() => openSearch('destination')}
          >
            <i className="dot end" />
            도착 <b>{destinationName}</b>
          </button>
        </div>
        <button
          className="icon-button summary-swap"
          aria-label="출발지와 도착지 교환"
          disabled={!canSwap}
          onClick={swapPlaces}
        >
          <ArrowLeftRight size={17} />
        </button>
      </div>
      <BottomSheet
        key="results"
        footer={
          status === 'success' &&
          !!selectedId &&
          visible.some((route) => route.id === selectedId) ? (
            <>
              <button className="secondary" onClick={() => go('detail')}>
                선택한 경로 상세
              </button>
              <button className="primary" onClick={startGuide}>
                이 경로로 안내
              </button>
            </>
          ) : undefined
        }
      >
        {status === 'loading' ? (
          <div className="empty" role="status">
            <span className="spinner" />
            <h2>경로를 찾고 있어요</h2>
          </div>
        ) : status === 'error' ? (
          <div className="empty" role="alert">
            <h2>{error || '경로를 불러오지 못했어요.'}</h2>
            <button className="primary" onClick={retry}>
              다시 시도
            </button>
          </div>
        ) : (
          <>
            <header className="row between results-header">
              <div>
                <h2>추천 경로</h2>
                <p>
                  {visible.length}개 경로{!liveApi && ' · 09:41 출발 기준'}
                </p>
              </div>
              <button className="secondary filter-button" onClick={openFilter}>
                <SlidersHorizontal size={16} />
                이동수단 <small>{enabled.length}/4</small>
              </button>
            </header>
            <div className="priority" role="group" aria-label="경로 우선순위">
              <button aria-pressed={priority === 'fast'} onClick={() => setPriority('fast')}>
                빠름 우선
              </button>
              <button
                aria-pressed={priority === 'calm'}
                disabled={!hasCongestion}
                onClick={() => setPriority('calm')}
              >
                덜 붐빔 우선
              </button>
            </div>
            <div className="route-list">
              {visible.map((route) => (
                <RouteCard
                  key={route.id}
                  route={route}
                  selected={selectedId === route.id}
                  onSelect={() => setSelectedId(route.id)}
                />
              ))}
            </div>
            {!visible.length && (
              <div className="empty">
                <Navigation />
                <h3>이 조건에 맞는 경로가 없어요</h3>
                <button className="secondary" onClick={openFilter}>
                  조건 변경
                </button>
              </div>
            )}
          </>
        )}
      </BottomSheet>
    </>
  )
}
