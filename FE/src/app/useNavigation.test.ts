// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { parseHash, parseScreen, screenTitles, useNavigation } from './useNavigation'

describe('해시 화면 식별', () => {
  it('운영자 뷰 화면 제목을 가진다', () => {
    expect(screenTitles.ops).toBe('운영자 뷰')
  })
  it('#ops는 활성일 때만 ops, 아니면 홈이다', () => {
    expect(parseScreen('#ops', true)).toBe('ops')
    expect(parseScreen('#ops', false)).toBe('home')
  })
  it('기존 화면과 알 수 없는 해시는 그대로 처리한다', () => {
    expect(parseScreen('#results', false)).toBe('results')
    expect(parseScreen('#unknown', true)).toBe('home')
    expect(parseScreen('', true)).toBe('home')
  })
  it('해시를 화면과 쿼리로 나눈다', () => {
    expect(parseHash('#results?from=a&to=b', false)).toEqual({
      screen: 'results',
      query: 'from=a&to=b',
    })
    expect(parseHash('#results', false)).toEqual({ screen: 'results', query: '' })
    expect(parseHash('#home?x=1', false)).toEqual({ screen: 'home', query: 'x=1' })
    expect(parseHash('#unknown?x=1', false).screen).toBe('home')
  })
})

describe('useNavigation', () => {
  beforeEach(() => {
    history.replaceState(null, '', '#home')
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('쿼리 붙은 해시로 시작하면 화면과 쿼리를 읽는다', () => {
    history.replaceState(null, '', '#results?from=a')
    const { result } = renderHook(() => useNavigation())
    expect(result.current.screen).toBe('results')
    expect(result.current.query).toBe('from=a')
  })

  it('go는 쿼리를 해시에 쓰고 상태를 갱신한다', () => {
    const { result } = renderHook(() => useNavigation())
    act(() => result.current.go('results', 'x=1'))
    expect(location.hash).toBe('#results?x=1')
    expect(result.current.screen).toBe('results')
    expect(result.current.query).toBe('x=1')
    act(() => result.current.go('home'))
    expect(location.hash).toBe('#home')
    expect(result.current.query).toBe('')
  })

  it('replace는 해시가 같으면 replaceState를 부르지 않는다', () => {
    history.replaceState(null, '', '#results?x=1')
    const { result } = renderHook(() => useNavigation())
    const spy = vi.spyOn(history, 'replaceState')
    act(() => result.current.replace('results', 'x=1'))
    expect(spy).not.toHaveBeenCalled()
    act(() => result.current.replace('results', 'x=2'))
    expect(spy).toHaveBeenCalledTimes(1)
    expect(location.hash).toBe('#results?x=2')
    expect(result.current.query).toBe('x=2')
  })

  it('hashchange로 화면과 쿼리를 갱신한다', () => {
    const { result } = renderHook(() => useNavigation())
    act(() => {
      history.replaceState(null, '', '#detail?y=2')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(result.current.screen).toBe('detail')
    expect(result.current.query).toBe('y=2')
  })
})
