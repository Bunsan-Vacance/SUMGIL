import { Navigation, Pencil, SlidersHorizontal } from 'lucide-react'
import BottomSheet from '../components/BottomSheet'
import RouteCard from '../features/route/RouteCard'
import type { Mode, Place, Priority, Route } from '../features/route/types'
import type { TripState } from '../features/route/tripReducer'
import type { Navigate } from '../app/useNavigation'
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
  openSearch: (target: 'destination') => void
  go: Navigate
  startGuide: () => void
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
  go,
  startGuide,
}: Props) {
  return (
    <>
      <div className="trip-summary">
        <div>
          <span>
            <i className="dot start" />
            출발 <b>{origin.name}</b>
          </span>
          <span>
            <i className="dot end" />
            도착 <b>{destinationName}</b>
          </span>
        </div>
        <button
          className="icon-button"
          aria-label="도착지 수정"
          onClick={() => openSearch('destination')}
        >
          <Pencil size={18} />
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
                <p>{visible.length}개 경로 · 09:41 출발 기준</p>
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
              <button aria-pressed={priority === 'calm'} onClick={() => setPriority('calm')}>
                덜 붐빔 우선
              </button>
            </div>
            {visible.some((r) => r.id === 'fast') && visible.some((r) => r.id === 'calm') && (
              <p className="comparison">
                덜 붐비는 길은 <strong>4분 더 걸리고 · 혼잡 2구간 감소</strong>
              </p>
            )}
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
