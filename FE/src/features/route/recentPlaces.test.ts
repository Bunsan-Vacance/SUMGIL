// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Place } from './types'
import {
  RECENT_PLACES_STORAGE_KEY,
  clearRecentPlaces,
  loadRecentPlaces,
  removeRecentPlace,
  saveRecentPlace,
} from './usePlaceSearch'

const place: Place = {
  id: 'station-1',
  name: '역삼역',
  address: '서울 강남구 테헤란로 지하 156',
  kind: '역',
  lat: 37.5006,
  lng: 127.0365,
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('최근 검색 장소 저장', () => {
  it('빈 값과 잘못된 저장값을 걸러서 불러온다', () => {
    localStorage.setItem(
      RECENT_PLACES_STORAGE_KEY,
      JSON.stringify([
        place,
        { ...place, id: 'station-2', name: '선릉역' },
        place,
        { ...place, id: '' },
        { ...place, id: 'missing-lng', lng: undefined },
        { ...place, id: 'bad-coordinate', lat: 999 },
      ]),
    )

    expect(loadRecentPlaces()).toEqual([place, { ...place, id: 'station-2', name: '선릉역' }])
    localStorage.setItem(RECENT_PLACES_STORAGE_KEY, '{bad json')
    expect(loadRecentPlaces()).toEqual([])
  })

  it('저장한 장소를 최신순으로 올리고 최대 10개만 유지한다', () => {
    for (let index = 0; index < 10; index += 1) {
      saveRecentPlace({ ...place, id: `place-${index}`, name: `장소 ${index}` })
    }
    expect(saveRecentPlace({ ...place, id: 'new-place', name: '새 장소' })).toHaveLength(10)
    expect(loadRecentPlaces()[0].id).toBe('new-place')

    const moved = saveRecentPlace({ ...place, id: 'place-4', name: '장소 4' })
    expect(moved).toHaveLength(10)
    expect(moved[0].id).toBe('place-4')
    expect(moved.filter(({ id }) => id === 'place-4')).toHaveLength(1)
  })

  it('개별 삭제와 전체 삭제를 저장한다', () => {
    saveRecentPlace(place)
    saveRecentPlace({ ...place, id: 'station-2', name: '선릉역' })
    expect(removeRecentPlace(place.id).map(({ id }) => id)).toEqual(['station-2'])
    expect(clearRecentPlaces()).toEqual([])
    expect(loadRecentPlaces()).toEqual([])
  })

  it('스토리지를 사용할 수 없어도 예외를 화면으로 전파하지 않는다', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })

    expect(loadRecentPlaces()).toEqual([])
    expect(saveRecentPlace(place)).toEqual([place])
    expect(removeRecentPlace(place.id)).toEqual([])
    expect(clearRecentPlaces()).toEqual([])
  })
})
