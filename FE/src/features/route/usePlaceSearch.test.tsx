// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlaceRepository } from '../../api/contracts'
import type { Place } from './types'
import { usePlaceSearch } from './usePlaceSearch'

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
