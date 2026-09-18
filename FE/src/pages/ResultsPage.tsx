import { useEffect, useId, useRef, useState } from 'react'
import { ArrowLeftRight, Check, ChevronDown, SlidersHorizontal, X } from 'lucide-react'
import DepartureTimeDialog from '../features/route/DepartureTimeDialog'
import RouteCard from '../features/route/RouteCard'
import type { Mode, Place, Priority, Route } from '../features/route/types'
import type { TripState } from '../features/route/tripReducer'
import type { Navigate } from '../app/useNavigation'
import { clockTime, congestionPredictionFor } from '../features/route/selectors'
import { busRouteOptions, groupRoutes } from '../features/route/routeGrouping'
import type { RepositoryErrorCode } from '../api/errors'

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
  onResetModes,
  onSearchWalk,
}: Props) {
  const [choosingTime, setChoosingTime] = useState(false)
  const [choosingSort, setChoosingSort] = useState(false)
  const sortControl = useRef<HTMLDivElement>(null)
  const sortTrigger = useRef<HTMLButtonElement>(null)
  const sortMenuId = useId()
  useEffect(() => {
    if (!choosingSort) return
    sortControl.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus()
    const dismiss = (event: PointerEvent) => {
      if (event.target instanceof Node && !sortControl.current?.contains(event.target)) {
        setChoosingSort(false)
      }
    }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [choosingSort])
  const liveApi = isLiveApi ?? false
  const routeGroups = groupRoutes(visible)
  const canSortByCongestion =
    visible.length > 1 &&
    visible.some((route) => route.routeType === 'LOW_CONGESTION' || congestionPredictionFor(route))
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
          {canSortByCongestion && (
            <div
              className="results-sort-control"
              ref={sortControl}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget)) setChoosingSort(false)
              }}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.preventDefault()
                  setChoosingSort(false)
                  sortTrigger.current?.focus()
                }
              }}
            >
              <button
                type="button"
                className="results-sort-trigger"
                ref={sortTrigger}
                aria-label={`경로 정렬: ${priority === 'fast' ? '빠른 순' : '덜 붐비는 순'}`}
                aria-haspopup="menu"
                aria-expanded={choosingSort}
                aria-controls={choosingSort ? sortMenuId : undefined}
                onClick={() => setChoosingSort((open) => !open)}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                    event.preventDefault()
                    setChoosingSort(true)
                  }
                }}
              >
                {priority === 'fast' ? '빠른 순' : '덜 붐비는 순'}
                <ChevronDown size={14} aria-hidden="true" />
              </button>
              {choosingSort && (
                <div
                  className="results-sort-menu"
                  id={sortMenuId}
                  role="menu"
                  aria-label="경로 정렬 기준"
                  onKeyDown={(event) => {
                    const items = Array.from(
                      event.currentTarget.querySelectorAll<HTMLButtonElement>('button'),
                    )
                    const index = items.indexOf(document.activeElement as HTMLButtonElement)
                    const next =
                      event.key === 'Home'
                        ? 0
                        : event.key === 'End'
                          ? items.length - 1
                          : event.key === 'ArrowDown'
                            ? (index + 1) % items.length
                            : event.key === 'ArrowUp'
                              ? (index + items.length - 1) % items.length
                              : -1
                    if (next >= 0) {
                      event.preventDefault()
                      items[next].focus()
                    }
                  }}
                >
                  {(['fast', 'calm'] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      role="menuitemradio"
                      aria-checked={priority === value}
                      onClick={() => {
                        setPriority(value)
                        setChoosingSort(false)
                        sortTrigger.current?.focus()
                      }}
                    >
                      {value === 'fast' ? '빠른 순' : '덜 붐비는 순'}
                      {priority === value && <Check size={18} aria-hidden="true" />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
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
            <div className="route-list">
              {routeGroups.map(({ representative: route, variants }) => {
                const busVariantCount = busRouteOptions(variants).length
                return (
                  <RouteCard
                    key={route.id}
                    route={route}
                    busVariantCount={busVariantCount > 1 ? busVariantCount : undefined}
                    onDetail={() => {
                      setSelectedId(route.id)
                      go('detail')
                    }}
                  />
                )
              })}
            </div>
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
