// @vitest-environment jsdom

import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SplashScreen, { SPLASH_DURATION_MS } from './SplashScreen'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('앱 시작 화면', () => {
  it('1.25초 뒤 완료 콜백을 호출한다', () => {
    vi.useFakeTimers()
    const onComplete = vi.fn()

    render(<SplashScreen onComplete={onComplete} />)

    expect(SPLASH_DURATION_MS).toBe(1250)
    expect(screen.getByRole('heading', { name: '숨은 길을 찾아 당신의 숨길을 열어 드립니다' })).toBeTruthy()
    act(() => vi.advanceTimersByTime(SPLASH_DURATION_MS - 1))
    expect(onComplete).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(1))
    expect(onComplete).toHaveBeenCalledOnce()
  })

  it('언마운트할 때 대기 중인 타이머를 정리한다', () => {
    vi.useFakeTimers()
    const clearTimeout = vi.spyOn(window, 'clearTimeout')
    const { unmount } = render(<SplashScreen onComplete={vi.fn()} />)

    unmount()

    expect(clearTimeout).toHaveBeenCalled()
  })
})
