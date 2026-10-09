// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Place } from './types'
import {
  FAVORITE_PLACES_STORAGE_KEY,
  isRegisterablePlace,
  loadFavoritePlaces,
  removeFavoritePlace,
  setFavoriteLabel,
  sortFavoritePlaces,
  toggleFavoritePlace,
} from './favoritePlaces'

const place: Place = {
  id: 'station-1',
  name: '역삼역',
  address: '서울 강남구 테헤란로 지하 156',
  kind: '역',
  lat: 37.5006,
  lng: 127.0365,
}
const other: Place = { ...place, id: 'station-2', name: '선릉역' }
const entry = (target: Place, label: 'home' | 'work' | null, savedAt: string) => ({
  place: target,
  label,
  savedAt,
})
const stored = () => JSON.parse(localStorage.getItem(FAVORITE_PLACES_STORAGE_KEY) ?? '[]')

beforeEach(() => localStorage.clear())
afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('즐겨찾기 장소 저장', () => {
  it('손상된 항목을 필드별로 걸러서 불러온다', () => {
    const at = '2026-10-01T00:00:00.000Z'
    localStorage.setItem(
      FAVORITE_PLACES_STORAGE_KEY,
      JSON.stringify([
        entry(place, null, at),
        'text',
        null,
        { label: null, savedAt: at },
        entry({ ...other, id: '' }, null, at),
        entry({ ...other, id: 'bad-label' }, 'office' as 'home', at),
        entry({ ...other, id: 'bad-date' }, null, 'not-a-date'),
        { place: { ...other, id: 'no-date' }, label: null },
        entry({ ...place, name: '중복' }, null, at),
        entry(other, null, at),
      ]),
    )
    expect(loadFavoritePlaces().map((item) => item.place.id)).toEqual(['station-1', 'station-2'])
    expect(loadFavoritePlaces()[0].place.name).toBe('역삼역')
    localStorage.setItem(FAVORITE_PLACES_STORAGE_KEY, '{bad json')
    expect(loadFavoritePlaces()).toEqual([])
    localStorage.setItem(FAVORITE_PLACES_STORAGE_KEY, '{}')
    expect(loadFavoritePlaces()).toEqual([])
  })

  it('현재 위치는 kind와 id 양쪽 경로 모두 등록할 수 없다', () => {
    const byKind: Place = { ...place, id: 'gps', kind: '현재 위치' }
    const byId: Place = { ...place, id: 'current-location:1', kind: '좌표' }
    expect(isRegisterablePlace(byKind)).toBe(false)
    expect(isRegisterablePlace(byId)).toBe(false)
    expect(isRegisterablePlace(place)).toBe(true)
    expect(toggleFavoritePlace(byKind)).toEqual([])
    expect(setFavoriteLabel(byId, 'home')).toEqual([])
    expect(loadFavoritePlaces()).toEqual([])
  })

  it('토글로 추가하고 다시 토글하면 label과 함께 제거한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-01T00:00:00.000Z'))
    expect(toggleFavoritePlace(place)).toEqual([entry(place, null, '2026-10-01T00:00:00.000Z')])
    setFavoriteLabel(place, 'home')
    expect(toggleFavoritePlace(place)).toEqual([])
    expect(stored()).toEqual([])
  })

  it('집과 회사는 각각 하나만 유지하고 라벨을 옮긴다', () => {
    setFavoriteLabel(place, 'home')
    const moved = setFavoriteLabel(other, 'home')
    expect(moved.find((item) => item.place.id === 'station-2')?.label).toBe('home')
    expect(moved.find((item) => item.place.id === 'station-1')?.label).toBeNull()
    expect(moved).toHaveLength(2)
    expect(moved.filter((item) => item.label === 'home')).toHaveLength(1)
  })

  it('불러올 때 중복된 집·회사는 첫 번째만 유지한다', () => {
    localStorage.setItem(
      FAVORITE_PLACES_STORAGE_KEY,
      JSON.stringify([
        entry(place, 'home', '2026-10-01T00:00:00.000Z'),
        entry(other, 'home', '2026-10-02T00:00:00.000Z'),
        entry({ ...place, id: 'station-3' }, 'work', '2026-10-03T00:00:00.000Z'),
        entry({ ...place, id: 'station-4' }, 'work', '2026-10-04T00:00:00.000Z'),
      ]),
    )
    const loaded = loadFavoritePlaces()
    expect(loaded.map((item) => [item.place.id, item.label])).toEqual([
      ['station-1', 'home'],
      ['station-3', 'work'],
      ['station-4', null],
      ['station-2', null],
    ])
  })

  it('20개를 넘으면 label 없는 가장 오래된 항목부터 제거한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-01T00:00:00.000Z'))
    setFavoriteLabel({ ...place, id: 'home-place' }, 'home')
    for (let index = 0; index < 19; index += 1) {
      vi.setSystemTime(new Date(Date.UTC(2026, 9, 2, 0, index)))
      toggleFavoritePlace({ ...place, id: `place-${index}` })
    }
    expect(loadFavoritePlaces()).toHaveLength(20)
    vi.setSystemTime(new Date(Date.UTC(2026, 9, 3)))
    const next = toggleFavoritePlace({ ...place, id: 'newest' })
    const ids = next.map((item) => item.place.id)
    expect(next).toHaveLength(20)
    expect(ids).toContain('home-place')
    expect(ids).toContain('newest')
    expect(ids).not.toContain('place-0')
    expect(ids).toContain('place-1')
  })

  it('집 → 회사 → 나머지 최신순으로 정렬한다', () => {
    const sorted = sortFavoritePlaces([
      entry({ ...place, id: 'old' }, null, '2026-10-01T00:00:00.000Z'),
      entry({ ...place, id: 'new' }, null, '2026-10-03T00:00:00.000Z'),
      entry({ ...place, id: 'work' }, 'work', '2026-10-01T00:00:00.000Z'),
      entry({ ...place, id: 'home' }, 'home', '2026-10-01T00:00:00.000Z'),
    ])
    expect(sorted.map((item) => item.place.id)).toEqual(['home', 'work', 'new', 'old'])
  })

  it('개별 삭제를 저장한다', () => {
    toggleFavoritePlace(place)
    toggleFavoritePlace(other)
    expect(removeFavoritePlace(place.id).map((item) => item.place.id)).toEqual(['station-2'])
    expect(stored()).toHaveLength(1)
  })

  it('스토리지를 사용할 수 없어도 예외를 화면으로 전파하지 않는다', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    expect(loadFavoritePlaces()).toEqual([])
    expect(toggleFavoritePlace(place).map((item) => item.place.id)).toEqual(['station-1'])
    expect(setFavoriteLabel(place, 'work')[0].label).toBe('work')
    expect(removeFavoritePlace(place.id)).toEqual([])
  })
})
