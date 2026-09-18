// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RouteRepository } from '../../api/contracts'
import { RepositoryError } from '../../api/errors'
import { places, routes } from '../../api/mock/fixtures'
import { previewTrip } from '../../app/preview'
import type { TripState } from './tripReducer'
import { useTrip } from './useTrip'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

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
  it('예측값 없는 실제 경로는 혼잡도 예측 없이 보존한다', async () => {
    const routeWithoutPrediction = { ...routes[0], congestionPrediction: undefined }
    const repository: RouteRepository = { search: vi.fn(async () => [routeWithoutPrediction]) }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))

    await act(async () => {
      await result.current.search(places[1])
    })

    expect(result.current.selected?.congestionPrediction).toBeUndefined()
  })

  it('쾌적 전환은 같은 조건으로 재조회하고 서버의 첫 후보를 선택한다', async () => {
    const serverRoutes = [
      { ...routes[1], routeType: 'LOW_CONGESTION' as const, minutes: 30 },
      { ...routes[0], routeType: 'SHORTEST' as const, minutes: 10 },
    ]
    const repository: RouteRepository = { search: vi.fn(async () => serverRoutes) }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))
    await act(async () => {
      await result.current.search(places[1])
    })
    const departedAt = vi.mocked(repository.search).mock.calls[0][0].departedAt
    act(() => result.current.setPriority('calm'))
    expect(result.current).toMatchObject({ status: 'loading', selected: null, candidates: [] })
    await waitFor(() => expect(result.current.status).toBe('success'))
    expect(repository.search).toHaveBeenLastCalledWith(
      expect.objectContaining({
        priority: 'calm',
        departedAt,
        modes: loadedTrip.enabled,
        origin: loadedTrip.origin,
        destination: places[1],
      }),
      expect.any(AbortSignal),
    )
    expect(result.current.visible).toEqual(serverRoutes)
    expect(result.current.selected).toEqual(serverRoutes[0])
  })

  it('빠른 우선순위 전환은 이전 요청을 취소하고 늦은 응답을 무시한다', async () => {
    const first = deferred<typeof routes>()
    const second = deferred<typeof routes>()
    const repository: RouteRepository = {
      search: vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise),
    }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))
    act(() => result.current.setPriority('calm'))
    act(() => result.current.setPriority('fast'))
    expect(vi.mocked(repository.search).mock.calls.map(([request]) => request.priority)).toEqual([
      'calm',
      'fast',
    ])
    expect(vi.mocked(repository.search).mock.calls[0][1].aborted).toBe(true)
    await act(async () => {
      second.resolve([routes[0]])
    })
    await act(async () => {
      first.resolve([routes[1]])
    })
    expect(result.current).toMatchObject({
      priority: 'fast',
      status: 'success',
      candidates: [routes[0]],
      selected: routes[0],
    })
  })

  it('쾌적 요청 실패 후 재시도에도 우선순위를 유지한다', async () => {
    const repository: RouteRepository = {
      search: vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([]),
    }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))
    act(() => result.current.setPriority('calm'))
    await waitFor(() => expect(result.current.status).toBe('error'))
    await act(async () => {
      await result.current.search(places[1])
    })
    expect(repository.search).toHaveBeenLastCalledWith(
      expect.objectContaining({ priority: 'calm' }),
      expect.any(AbortSignal),
    )
    expect(result.current).toMatchObject({ status: 'success', candidates: [], selected: null })
  })

  it('검색 전 우선순위 변경과 동일 우선순위 선택은 불필요한 요청을 만들지 않는다', async () => {
    const repository: RouteRepository = { search: vi.fn(async () => routes) }
    const { result } = renderHook(() => useTrip(previewTrip, repository))
    act(() => result.current.setPriority('calm'))
    expect(repository.search).not.toHaveBeenCalled()
    await act(async () => {
      await result.current.search(places[1])
    })
    act(() => result.current.setPriority('calm'))
    expect(repository.search).toHaveBeenCalledOnce()
    expect(repository.search).toHaveBeenLastCalledWith(
      expect.objectContaining({ priority: 'calm' }),
      expect.any(AbortSignal),
    )
  })
  it('검색 요청에 현재 선택한 이동수단을 전달한다', async () => {
    const repository: RouteRepository = { search: vi.fn(async () => routes) }
    const { result } = renderHook(() => useTrip(previewTrip, repository))

    await act(async () => {
      await result.current.search(places[1])
    })

    expect(repository.search).toHaveBeenCalledWith(
      {
        origin: previewTrip.origin,
        destination: places[1],
        modes: previewTrip.enabled,
        priority: 'fast',
        departedAt: expect.any(String),
      },
      expect.any(AbortSignal),
    )
  })

  it('성공한 검색 뒤 필터를 바꾸면 도보를 포함해 재검색한다', async () => {
    const repository: RouteRepository = { search: vi.fn(async () => routes) }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))

    act(() => result.current.setModes(['bike']))
    await waitFor(() => expect(repository.search).toHaveBeenCalledOnce())

    expect(repository.search).toHaveBeenCalledWith(
      {
        origin: loadedTrip.origin,
        destination: loadedTrip.destination,
        modes: ['walk', 'bike'],
        priority: 'fast',
        departedAt: expect.any(String),
      },
      expect.any(AbortSignal),
    )
  })

  it('필터 재검색은 진행 중인 이전 요청을 취소하고 늦은 결과를 무시한다', async () => {
    const first = deferred<typeof routes>()
    const second = deferred<typeof routes>()
    const repository: RouteRepository = {
      search: vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise),
    }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))

    act(() => result.current.setModes(['bike']))
    act(() => result.current.setModes(['bus']))

    expect(vi.mocked(repository.search).mock.calls[0][1].aborted).toBe(true)
    await act(async () => {
      first.resolve(routes)
      await Promise.resolve()
    })
    expect(result.current).toMatchObject({ candidates: [], status: 'loading' })

    await act(async () => {
      second.resolve([])
      await Promise.resolve()
    })
    expect(result.current).toMatchObject({ candidates: [], selected: null, status: 'success' })
  })

  it('idle 상태에서 필터 변경은 검색하지 않는다', () => {
    const repository: RouteRepository = { search: vi.fn(async () => routes) }
    const { result } = renderHook(() => useTrip(previewTrip, repository))

    act(() => result.current.setModes(['bike']))

    expect(repository.search).not.toHaveBeenCalled()
    expect(result.current).toMatchObject({ enabled: ['walk', 'bike'], status: 'idle' })
  })

  it('resetModes는 검색된 상태에서 모든 수단으로 다시 요청한다', async () => {
    const filteredTrip: TripState = { ...loadedTrip, enabled: ['walk', 'bike'] }
    const repository: RouteRepository = { search: vi.fn(async () => routes) }
    const { result } = renderHook(() => useTrip(filteredTrip, repository))

    act(() => result.current.resetModes())
    await waitFor(() => expect(repository.search).toHaveBeenCalledOnce())

    expect(repository.search).toHaveBeenCalledWith(
      {
        origin: filteredTrip.origin,
        destination: filteredTrip.destination,
        modes: ['walk', 'bike', 'bus', 'subway'],
        priority: 'fast',
        departedAt: expect.any(String),
      },
      expect.any(AbortSignal),
    )
  })

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

  it('RepositoryError 메시지는 사용자에게 전달하고 일반 오류는 기본 문구를 유지한다', async () => {
    const repository: RouteRepository = {
      search: vi
        .fn()
        .mockRejectedValueOnce(new RepositoryError('station-not-found', '역 정보를 찾지 못했어요.'))
        .mockRejectedValueOnce(new Error('internal details')),
    }
    const { result } = renderHook(() => useTrip(previewTrip, repository))

    await act(async () => {
      await result.current.search(places[1])
    })
    expect(result.current).toMatchObject({
      error: '역 정보를 찾지 못했어요.',
      errorCode: 'station-not-found',
    })

    await act(async () => {
      await result.current.search(places[1])
    })
    expect(result.current.error).toBe('경로를 불러오지 못했어요.')
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
      {
        origin: places[3],
        destination: places[1],
        modes: loadedTrip.enabled,
        priority: 'fast',
        departedAt: expect.any(String),
      },
      expect.any(AbortSignal),
    )
    expect(result.current).toMatchObject({ origin: places[3], destination: places[1] })
  })

  it('선택한 출발 시각을 서울 날짜의 ISO 시각으로 요청하고 재검색에도 유지한다', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-15T00:30:00.000Z'))
    const repository: RouteRepository = { search: vi.fn(async () => routes) }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))

    await act(async () => {
      result.current.setDepartureTime('09:15')
      await Promise.resolve()
    })
    expect(result.current.departureTime).toBe('09:15')
    expect(repository.search).toHaveBeenLastCalledWith(
      expect.objectContaining({ departedAt: '2026-09-15T00:15:00.000Z' }),
      expect.any(AbortSignal),
    )

    await act(async () => {
      await result.current.search(places[1])
    })
    expect(repository.search).toHaveBeenLastCalledWith(
      expect.objectContaining({ departedAt: '2026-09-15T00:15:00.000Z' }),
      expect.any(AbortSignal),
    )
  })

  it('잘못된 출발 시각은 상태와 검색을 바꾸지 않는다', () => {
    const repository: RouteRepository = { search: vi.fn(async () => routes) }
    const { result } = renderHook(() => useTrip(loadedTrip, repository))

    let accepted!: boolean
    act(() => {
      accepted = result.current.setDepartureTime('24:00')
    })

    expect(accepted).toBe(false)
    expect(result.current.departureTime).toBeNull()
    expect(repository.search).not.toHaveBeenCalled()
  })
})
