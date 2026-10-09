// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Place } from './types'
import {
  RECENT_ROUTES_STORAGE_KEY,
  formatSearchedAt,
  isRecentRoutePinned,
  pinRecentRoute,
  loadRecentRoutes,
  recentRouteId,
  removeRecentRoute,
  saveRecentRoute,
  sortRecentRoutes,
} from './recentRoutes'
import type { RecentRoute } from './recentRoutes'

const origin: Place = {
  id: 'station-1',
  name: '역삼역',
  address: '서울 강남구 테헤란로 지하 156',
  kind: '역',
  lat: 37.5006,
  lng: 127.0365,
}
const destination: Place = { ...origin, id: 'station-2', name: '선릉역' }
const at = '2026-10-01T00:00:00.000Z'
const route = (
  from: Place | null,
  to: Place,
  overrides: Partial<RecentRoute> = {},
): RecentRoute => ({
  id: recentRouteId(from, to),
  origin: from,
  destination: to,
  searchedAt: at,
  pinned: false,
  ...overrides,
})
const stored = () => JSON.parse(localStorage.getItem(RECENT_ROUTES_STORAGE_KEY) ?? '[]')

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('최근 경로 저장', () => {
  it('손상된 항목과 id가 맞지 않는 항목을 걸러서 불러온다', () => {
    localStorage.setItem(
      RECENT_ROUTES_STORAGE_KEY,
      JSON.stringify([
        route(origin, destination),
        route(origin, destination, { searchedAt: '2026-10-02T00:00:00.000Z' }),
        'text',
        null,
        { ...route(origin, destination), destination: { ...destination, id: '' } },
        { ...route(origin, { ...destination, id: 'x' }), origin: { ...origin, id: '' } },
        route(null, { ...destination, id: 'bad-date' }, { searchedAt: 'not-a-date' }),
        { ...route(null, { ...destination, id: 'bad-pin' }), pinned: 'yes' },
        { ...route(null, { ...destination, id: 'no-pin' }), pinned: undefined },
        { ...route(origin, { ...destination, id: 'bad-id' }), id: 'other' },
        route(null, { ...destination, id: 'ok-null' }),
      ]),
    )
    expect(loadRecentRoutes().map((item) => item.id)).toEqual([
      'station-1>station-2',
      'current-location>ok-null',
    ])
    localStorage.setItem(RECENT_ROUTES_STORAGE_KEY, '{bad json')
    expect(loadRecentRoutes()).toEqual([])
  })

  it('현재 위치 출발은 origin을 null로 저장한다', () => {
    const byKind: Place = { ...origin, id: 'gps', kind: '현재 위치' }
    const byId: Place = { ...origin, id: 'current-location:37.5:127', kind: '좌표' }
    expect(saveRecentRoute(byKind, destination)[0].origin).toBeNull()
    expect(saveRecentRoute(byId, destination)).toHaveLength(1)
    expect(stored()[0].id).toBe('current-location>station-2')
  })

  it('잘못된 장소는 저장하지 않는다', () => {
    expect(saveRecentRoute(origin, { ...destination, id: '' })).toEqual([])
    expect(saveRecentRoute({ ...origin, name: '' }, destination)).toEqual([])
  })

  it('같은 경로를 다시 저장하면 시각만 갱신하고 고정 상태를 유지한다', () => {
    const other: Place = { ...destination, id: 'station-3' }
    saveRecentRoute(origin, destination, new Date(at))
    saveRecentRoute(origin, other, new Date('2026-10-02T00:00:00.000Z'))
    localStorage.setItem(
      RECENT_ROUTES_STORAGE_KEY,
      JSON.stringify(
        loadRecentRoutes().map((item) => ({
          ...item,
          pinned: item.destination.id === 'station-2',
        })),
      ),
    )
    const next = saveRecentRoute(origin, destination, new Date('2026-10-03T00:00:00.000Z'))
    expect(next).toHaveLength(2)
    expect(next[0].id).toBe('station-1>station-2')
    expect(next[0].pinned).toBe(true)
    expect(next[0].searchedAt).toBe('2026-10-03T00:00:00.000Z')
  })

  it('최신 시각으로 다시 저장하면 고정되지 않은 항목은 맨 앞으로 이동한다', () => {
    saveRecentRoute(origin, destination, new Date(at))
    saveRecentRoute(
      origin,
      { ...destination, id: 'station-3' },
      new Date('2026-10-02T00:00:00.000Z'),
    )
    const next = saveRecentRoute(origin, destination, new Date('2026-10-03T00:00:00.000Z'))
    expect(next.map((item) => item.id)).toEqual(['station-1>station-2', 'station-1>station-3'])
  })

  it('10개를 넘으면 고정되지 않은 가장 오래된 것부터 제거한다', () => {
    const pinnedRoute = route(origin, { ...destination, id: 'pinned' }, { pinned: true })
    localStorage.setItem(RECENT_ROUTES_STORAGE_KEY, JSON.stringify([pinnedRoute]))
    for (let index = 0; index < 9; index += 1) {
      saveRecentRoute(
        origin,
        { ...destination, id: `d-${index}` },
        new Date(Date.UTC(2026, 9, 2, 0, index)),
      )
    }
    expect(loadRecentRoutes()).toHaveLength(10)
    const next = saveRecentRoute(
      origin,
      { ...destination, id: 'newest' },
      new Date(Date.UTC(2026, 9, 3)),
    )
    const ids = next.map((item) => item.destination.id)
    expect(next).toHaveLength(10)
    expect(ids).toContain('pinned')
    expect(ids).toContain('newest')
    expect(ids).not.toContain('d-0')
    expect(ids).toContain('d-1')
  })

  it('고정 항목을 먼저, 그 안에서 최신순으로 정렬한다', () => {
    const sorted = sortRecentRoutes([
      route(origin, { ...destination, id: 'old' }),
      route(origin, { ...destination, id: 'new' }, { searchedAt: '2026-10-03T00:00:00.000Z' }),
      route(origin, { ...destination, id: 'pin' }, { pinned: true }),
    ])
    expect(sorted.map((item) => item.destination.id)).toEqual(['pin', 'new', 'old'])
  })

  it('개별 삭제를 저장한다', () => {
    saveRecentRoute(origin, destination)
    saveRecentRoute(origin, { ...destination, id: 'station-3' })
    expect(removeRecentRoute('station-1>station-2').map((item) => item.id)).toEqual([
      'station-1>station-3',
    ])
    expect(stored()).toHaveLength(1)
  })

  it('스토리지를 사용할 수 없어도 예외를 화면으로 전파하지 않는다', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    expect(loadRecentRoutes()).toEqual([])
    expect(saveRecentRoute(origin, destination)).toHaveLength(1)
    expect(removeRecentRoute('station-1>station-2')).toEqual([])
  })
})

describe('검색 시각 표시', () => {
  const now = new Date('2026-10-09T03:00:00.000Z')
  it('오늘은 시각, 어제는 어제, 그 외는 월일로 표시한다', () => {
    expect(formatSearchedAt('2026-10-09T00:30:00.000Z', now)).toBe('오늘 09:30')
    expect(formatSearchedAt('2026-10-08T05:00:00.000Z', now)).toBe('어제')
    expect(formatSearchedAt('2026-10-02T05:00:00.000Z', now)).toBe('10월 2일')
  })
  it('날짜 경계는 Asia/Seoul 기준이다', () => {
    // UTC로는 같은 날 15:30이지만 서울은 이미 다음 날 00:30이다.
    expect(formatSearchedAt('2026-10-08T15:30:00.000Z', now)).toBe('오늘 00:30')
    expect(formatSearchedAt('2026-10-08T14:59:00.000Z', now)).toBe('어제')
  })
})

describe('경로 저장(고정)', () => {
  it('새 경로를 pinned로 추가한다', () => {
    const next = pinRecentRoute(origin, destination, new Date(at))
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ pinned: true, searchedAt: at })
  })

  it('기존 경로는 검색 시각을 유지한 채 pinned로 올린다', () => {
    saveRecentRoute(origin, destination, new Date(at))
    const next = pinRecentRoute(origin, destination, new Date('2026-10-05T00:00:00.000Z'))
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ pinned: true, searchedAt: at })
  })

  it('현재 위치 출발은 origin을 null로 저장한다', () => {
    const current: Place = { ...origin, id: 'gps', kind: '현재 위치' }
    expect(pinRecentRoute(current, destination)[0].origin).toBeNull()
  })

  it('저장 여부를 확인한다', () => {
    expect(isRecentRoutePinned(origin, destination)).toBe(false)
    saveRecentRoute(origin, destination)
    expect(isRecentRoutePinned(origin, destination)).toBe(false)
    pinRecentRoute(origin, destination)
    expect(isRecentRoutePinned(origin, destination)).toBe(true)
  })

  it('pinned가 한도를 넘어도 제거하지 않는다', () => {
    for (let index = 0; index < 11; index += 1) {
      pinRecentRoute(origin, { ...destination, id: 'p-' + index })
    }
    expect(loadRecentRoutes()).toHaveLength(11)
  })
})
