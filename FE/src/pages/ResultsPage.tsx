import { useState } from 'react'
import { ArrowLeftRight, ChevronDown, SlidersHorizontal, X } from 'lucide-react'
import DepartureTimeDialog from '../features/route/DepartureTimeDialog'
import RouteCard from '../features/route/RouteCard'
import type { Mode, Place, Priority, Route } from '../features/route/types'
import type { TripState } from '../features/route/tripReducer'
import type { Navigate } from '../app/useNavigation'
import { clockTime, congestionPredictionFor } from '../features/route/selectors'
import { groupRoutes } from '../features/route/routeGrouping'
import type { RepositoryErrorCode } from '../api/errors'
import { useScrollbarVisibility } from '../components/useScrollbarVisibility'

interface Props {
  origin: Place
  destinationName: string
  visible: Route[]
  selectedId: string | null
  setSelectedId: (id: string) => void
  status: TripState['status']
  retry: () => void
  error: string
  errorCode?: RepositoryErrorCode | null
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
  onResetModes?: () => void
  onSearchWalk?: () => void
}

type Recommendation = 'fast' | 'calm'

interface FeaturedRoute {
  route: Route
  recommendations: Recommendation[]
}

function compareByTime(a: Route, b: Route, aIndex: number, bIndex: number) {
  return a.minutes - b.minutes || aIndex - bIndex
}

function sortRoutes(routes: Route[], priority: Priority) {
  return routes
    .map((route, index) => ({
      route,
      index,
      prediction: congestionPredictionFor(route)?.congestionPercent,
    }))
    .sort((a, b) => {
      if (priority === 'fast') return compareByTime(a.route, b.route, a.index, b.index)
      if (a.prediction !== undefined && b.prediction !== undefined) {
        return a.prediction - b.prediction || compareByTime(a.route, b.route, a.index, b.index)
      }
      if (a.prediction !== undefined) return -1
      if (b.prediction !== undefined) return 1
      return compareByTime(a.route, b.route, a.index, b.index)
    })
    .map(({ route }) => route)
}

function featuredRoutes(routes: Route[]): FeaturedRoute[] {
  if (!routes.length) return []
  const fastest = routes.reduce(
    (best, route, index) =>
      !best || compareByTime(route, best.route, index, best.index) < 0 ? { route, index } : best,
    undefined as { route: Route; index: number } | undefined,
  )
  const taggedCalm = routes.filter((route) => route.routeType === 'LOW_CONGESTION')
  const calmCandidates = taggedCalm.length
    ? taggedCalm
    : routes.filter((route) => congestionPredictionFor(route) !== undefined)
  const calm = calmCandidates.reduce<Route | undefined>((best, route) => {
    if (!best) return route
    if (taggedCalm.length) return compareByTime(route, best, 0, 0) < 0 ? route : best
    const routePercent = congestionPredictionFor(route)?.congestionPercent
    const bestPercent = congestionPredictionFor(best)?.congestionPercent
    if (routePercent === undefined || bestPercent === undefined) return best
    return routePercent < bestPercent ||
      (routePercent === bestPercent && route.minutes < best.minutes)
      ? route
      : best
  }, undefined)
  const result: FeaturedRoute[] = []
  if (fastest) result.push({ route: fastest.route, recommendations: ['fast'] })
  if (calm) {
    const existing = result.find((entry) => entry.route.id === calm.id)
    if (existing) existing.recommendations.push('calm')
    else result.push({ route: calm, recommendations: ['calm'] })
  }
  return result
}

export default function ResultsPage({
  origin,
  destinationName,
  visible,
  setSelectedId,
  status,
  retry,
  error,
  errorCode,
  enabled,
  priority,
  openFilter,
  openSearch,
  onBackToInput,
  go,
  canSwap,
  swapPlaces,
  isLiveApi,
  departureTime,
  onDepartureTimeChange,
  onResetModes,
  onSearchWalk,
}: Props) {
  const resultsRef = useScrollbarVisibility<HTMLDivElement>()
  const [choosingTime, setChoosingTime] = useState(false)
  const [localPriority, setLocalPriority] = useState<Priority>(() => priority)
  const liveApi = isLiveApi ?? false
  const featured = featuredRoutes(visible)
  const featuredIds = new Set(featured.map(({ route }) => route.id))
  const remaining = visible.filter((route) => !featuredIds.has(route.id))
  const remainingPredictions = remaining.filter((route) => congestionPredictionFor(route))
  const canSortByCongestion = remaining.length > 1 && remainingPredictions.length > 0
  const sortPriority = localPriority === 'calm' && !canSortByCongestion ? 'fast' : localPriority
  const remainingGroups = groupRoutes(sortRoutes(remaining, sortPriority))
  const departure = departureTime || clockTime(visible[0]?.departedAt)
  const errorTitle =
    errorCode === 'access-candidate-not-found'
      ? '출발지나 도착지 주변에 연결되는 경로가 없어요.'
      : errorCode === 'out-of-service-area'
        ? '서비스 지역 밖이라 경로를 찾지 못했어요.'
        : errorCode === 'service-ended'
          ? '선택한 출발 시간에는 이용할 수 없어요.'
          : error || '경로를 불러오지 못했어요.'

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
      </header>

      <div ref={resultsRef} className="results-scroll scrollbar-auto">
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
        </div>

        {status === 'loading' ? (
          <div className="empty results-state" role="status">
            <span className="spinner" />
            <h2>경로를 찾고 있어요</h2>
          </div>
        ) : status === 'error' ? (
          <div className="empty results-state" role="alert">
            <h2>{errorTitle}</h2>
            {errorCode === 'access-candidate-not-found' && (
              <p>출발지·도착지 주변에 연결되는 경로가 있는지 확인해 보세요.</p>
            )}
            {errorCode === 'out-of-service-area' && (
              <p>출발지와 도착지를 서비스 지역 안에서 선택해 주세요.</p>
            )}
            {errorCode === 'service-ended' && (
              <p>출발 시간을 바꾸거나 다른 이동수단을 선택해 보세요.</p>
            )}
            <div className="results-recovery-actions">
              {errorCode === 'out-of-service-area' ? (
                <button className="primary" onClick={onBackToInput}>
                  출발·도착지 수정
                </button>
              ) : errorCode === 'access-candidate-not-found' ? (
                <>
                  <button className="primary" onClick={onBackToInput}>
                    출발·도착지 수정
                  </button>
                  <button className="secondary" onClick={openFilter}>
                    이동수단 변경
                  </button>
                </>
              ) : errorCode === 'service-ended' ? (
                <>
                  <button className="primary" onClick={() => setChoosingTime(true)}>
                    출발 시간 변경
                  </button>
                  <button className="secondary" onClick={openFilter}>
                    이동수단 변경
                  </button>
                </>
              ) : (
                <button className="primary" onClick={retry}>
                  다시 시도
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            {!liveApi && <p className="results-sample">시안 · 예시 데이터</p>}
            {featured.length > 0 && (
              <section className="route-section" aria-labelledby="recommended-routes-heading">
                <div className="route-section-heading">
                  <h2 id="recommended-routes-heading">추천 경로</h2>
                </div>
                <div className="route-list">
                  {featured.map(({ route, recommendations }) => (
                    <RouteCard
                      key={route.id}
                      route={route}
                      recommendations={recommendations}
                      onDetail={() => {
                        setSelectedId(route.id)
                        go('detail')
                      }}
                    />
                  ))}
                </div>
              </section>
            )}
            {remainingGroups.length > 0 && (
              <section className="route-section" aria-labelledby="other-routes-heading">
                <div className="route-section-heading route-section-heading-with-sort">
                  <h2 id="other-routes-heading">다른 경로</h2>
                  <div className="route-sort-segmented" role="group" aria-label="다른 경로 정렬">
                    <button
                      type="button"
                      aria-pressed={sortPriority === 'fast'}
                      onClick={() => setLocalPriority('fast')}
                    >
                      빠른 순
                    </button>
                    <button
                      type="button"
                      aria-pressed={sortPriority === 'calm'}
                      disabled={!canSortByCongestion}
                      onClick={() => setLocalPriority('calm')}
                    >
                      덜 붐비는 순
                    </button>
                  </div>
                </div>
                <div className="route-list">
                  {remainingGroups.map(({ representative: route }) => (
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
              </section>
            )}
            {!visible.length && (
              <div className="empty">
                <h3>해당 수단으로는 경로가 없어요</h3>
                {onResetModes && (
                  <button className="primary" onClick={onResetModes}>
                    전체 수단으로 다시 검색
                  </button>
                )}
                {onSearchWalk && (
                  <button className="secondary" onClick={onSearchWalk}>
                    도보만 다시 검색
                  </button>
                )}
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
