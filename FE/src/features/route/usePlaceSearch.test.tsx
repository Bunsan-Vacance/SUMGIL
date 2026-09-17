// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlaceRepository, StationRepository } from '../../api/contracts'
import type { Place } from './types'
import {
  RECENT_PLACES_STORAGE_KEY,
  loadRecentPlaces,
  stationSearchResultToPlace,
  usePlaceSearch,
  useStationSearch,
} from './usePlaceSearch'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const result: Place = {
  id: 'station-1',
  name: '역삼역',
  address: '서울 강남구 테헤란로 지하 156',
  kind: '역',
  lat: 37.5006,
  lng: 127.0365,
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((yes) => {
    resolve = yes
  })
  return { promise, resolve }
}

describe('장소 검색 요청', () => {
  it('빈 검색어를 요청하지 않고 300ms debounce 뒤 trim된 검색어를 보낸다', async () => {
    vi.useFakeTimers()
    const repository: PlaceRepository = { search: vi.fn(async () => [result]) }
    const { result: hook, rerender } = renderHook(
      ({ query }) => usePlaceSearch(query, repository),
      { initialProps: { query: '' } },
    )

    expect(repository.search).not.toHaveBeenCalled()
    rerender({ query: ' 역삼역 ' })
    act(() => vi.advanceTimersByTime(299))
    expect(repository.search).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(1)
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(repository.search).toHaveBeenCalledWith('역삼역', expect.any(AbortSignal))
    expect(hook.current.places).toEqual([result])
  })

  it('새 검색은 이전 요청을 취소하고 늦은 응답을 버린다', async () => {
    const first = deferred<Place[]>()
    const second = deferred<Place[]>()
    const repository: PlaceRepository = {
      search: vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise),
    }
    const { result: hook, rerender } = renderHook(
      ({ query }) => usePlaceSearch(query, repository),
      { initialProps: { query: '역삼역' } },
    )
    await new Promise((resolve) => setTimeout(resolve, 310))
    rerender({ query: '테헤란로' })
    await new Promise((resolve) => setTimeout(resolve, 310))
    expect(vi.mocked(repository.search).mock.calls[0][1].aborted).toBe(true)
    await act(async () => {
      first.resolve([{ ...result, id: 'stale' }])
      second.resolve([result])
      await Promise.all([first.promise, second.promise])
    })
    expect(hook.current.places).toEqual([result])
  })

  it('검색 오류는 오류 상태로 표시한다', async () => {
    const repository: PlaceRepository = {
      search: vi.fn(async () => {
        throw new Error('failed')
      }),
    }
    const { result: hook } = renderHook(() => usePlaceSearch('없는 장소', repository))
    await new Promise((resolve) => setTimeout(resolve, 310))
    await waitFor(() => expect(hook.current.error).toContain('검색하지 못했어요'))
    expect(hook.current.places).toEqual([])
  })
})

describe('역 검색 요청', () => {
  it('역 검색 결과의 stationId를 경로 입력 장소에 그대로 보존한다', async () => {
    vi.useFakeTimers()
    const stationRepository: StationRepository = {
      search: vi.fn(async () => [
        {
          stationId: '214',
          stationName: '강변',
          lineId: '1002',
          lineName: '2호선',
          lat: 37.535161,
          lng: 127.094684,
        },
      ]),
    }
    const { result: hook } = renderHook(() => useStationSearch(' 강변역 ', stationRepository))

    await act(async () => {
      vi.advanceTimersByTime(300)
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(hook.current.stations[0].stationId).toBe('214')
    expect(stationSearchResultToPlace(hook.current.stations[0])).toMatchObject({
      id: 'station:214:1002',
      name: '강변 (2호선)',
      stationId: '214',
      kind: '지하철역',
    })
  })

  it('최근 장소의 영문 stationId를 보존하고 공백 stationId는 거부한다', () => {
    localStorage.setItem(
      RECENT_PLACES_STORAGE_KEY,
      JSON.stringify([
        { ...result, stationId: '150' },
        { ...result, id: 'station-s410', stationId: 'S410' },
        { ...result, id: 'station-blank', stationId: '   ' },
      ]),
    )

    expect(loadRecentPlaces().map((place) => place.stationId)).toEqual(['150', 'S410'])
  })

  it('백엔드가 설정되지 않은 환경에서는 역 검색 요청을 만들지 않는다', async () => {
    const { result: hook } = renderHook(() => useStationSearch('강변', null))

    await waitFor(() => expect(hook.current.loading).toBe(false))
    expect(hook.current.stations).toEqual([])
  })
})
