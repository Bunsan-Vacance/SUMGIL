import { useEffect, useId, useRef, useState } from 'react'
import { ArrowLeftRight, Check, ChevronDown, SlidersHorizontal, X } from 'lucide-react'
import DepartureTimeDialog from '../features/route/DepartureTimeDialog'
import RouteCard from '../features/route/RouteCard'
import type { Mode, Place, Priority, Route } from '../features/route/types'
import type { TripState } from '../features/route/tripReducer'
import type { Navigate } from '../app/useNavigation'
import { clockTime, roundMinutes } from '../features/route/selectors'
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
  const liveApi = isLiveApi ?? isBackendConfigured
  const canSortByCongestion =
    liveApi ||
    (visible.length > 1 && visible.every((route) => route.routeType !== undefined)) ||
    (visible.length > 1 && visible.every((route) => route.congestionPercent !== undefined))
  const departure = departureTime || clockTime(visible[0]?.departedAt)
  const fastestRoute = visible.reduce<Route | undefined>(
    (fastest, route) => (!fastest || route.minutes < fastest.minutes ? route : fastest),
    undefined,
  )

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
                  comparison={
                    fastestRoute?.congestionPercent !== undefined &&
                    route.congestionPercent !== undefined &&
                    route.minutes > fastestRoute.minutes &&
                    route.congestionPercent < fastestRoute.congestionPercent
                      ? `${roundMinutes(route.minutes - fastestRoute.minutes)}분 더 걸림 · 혼잡도 ${Math.round(fastestRoute.congestionPercent - route.congestionPercent)}%p 낮음`
                      : undefined
                  }
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
