// @vitest-environment jsdom

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RouteRepository } from '../../api/contracts'
import { places, routes } from '../../api/mock/fixtures'
import { previewTrip } from '../../app/preview'
import type { TripState } from './tripReducer'
import { useTrip } from './useTrip'

afterEach(cleanup)

const loadedTrip: TripState = {
  ...previewTrip,
  destination: places[1],
  candidates: routes,
  selected: routes[0],
  status: 'success',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((yes) => {
    resolve = yes
  })
  return { promise, resolve }
}

describe('경로 검색 요청 수명', () => {
  it('실패한 검색을 같은 조건으로 재시도하면 오류를 지우고 새 결과를 선택한다', async () => {
    const repository: RouteRepository = {
      search: vi
        .fn()
        .mockRejectedValueOnce(new Error('temporary failure'))
        .mockResolvedValueOnce(routes),
    }
    const { result } = renderHook(() => useTrip(previewTrip, repository))

    await act(async () => {
      await result.current.search(places[1])
    })
    expect(result.current).toMatchObject({
      destination: places[1],
      candidates: [],
      selected: null,
      status: 'error',
      error: '경로를 불러오지 못했어요.',
    })

    await act(async () => {
      await result.current.search(places[1])
    })
    expect(repository.search).toHaveBeenCalledTimes(2)
    expect(result.current).toMatchObject({
      destination: places[1],
      candidates: routes,
      selected: routes[0],
      status: 'success',
      error: '',
    })
  })

  it('새 검색은 이전 경로를 즉시 숨기고 앞선 요청의 늦은 응답을 무시한다', async () => {
    const first = deferred<typeof routes>()
    const second = deferred<typeof routes>()
    const repository: RouteRepository = {
      search: vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise),
    }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))

    let firstSearch!: Promise<void>
    act(() => {
      firstSearch = result.current.search(places[2])
    })
    expect(result.current).toMatchObject({
      destination: places[2],
      candidates: [],
      selected: null,
      status: 'loading',
    })

    let secondSearch!: Promise<void>
    act(() => {
      secondSearch = result.current.search(places[3])
    })
    expect(vi.mocked(repository.search).mock.calls[0][1].aborted).toBe(true)

    await act(async () => {
      first.resolve(routes)
      await firstSearch
    })
    expect(result.current).toMatchObject({
      destination: places[3],
      candidates: [],
      status: 'loading',
    })

    await act(async () => {
      second.resolve([])
      await secondSearch
    })
    expect(result.current).toMatchObject({ candidates: [], selected: null, status: 'success' })
  })

  it('출발지 변경은 진행 중 요청을 취소하고 기존 결과를 복원하지 않는다', async () => {
    const pending = deferred<typeof routes>()
    const repository: RouteRepository = { search: vi.fn(() => pending.promise) }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))

    let search!: Promise<void>
    act(() => {
      search = result.current.search(places[2])
    })
    act(() => result.current.setOrigin(places[3]))

    expect(vi.mocked(repository.search).mock.calls[0][1].aborted).toBe(true)
    expect(result.current).toMatchObject({
      origin: places[3],
      candidates: [],
      selected: null,
      status: 'idle',
    })

    await act(async () => {
      pending.resolve(routes)
      await search
    })
    expect(result.current).toMatchObject({ candidates: [], selected: null, status: 'idle' })
  })

  it('새 출발지를 명시한 재검색은 최신 출발지와 기존 목적지를 함께 보낸다', async () => {
    const repository: RouteRepository = { search: vi.fn(async () => routes) }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))

    await act(async () => {
      await result.current.search(places[1], places[3])
    })

    expect(repository.search).toHaveBeenCalledWith(
      { origin: places[3], destination: places[1] },
      expect.any(AbortSignal),
    )
    expect(result.current).toMatchObject({ origin: places[3], destination: places[1] })
  })
})
