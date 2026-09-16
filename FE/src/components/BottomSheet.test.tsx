// @vitest-environment jsdom

import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import BottomSheet from './BottomSheet'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('BottomSheet 스크롤바', () => {
  it('스크롤 중에 보이고 마지막 스크롤 700ms 뒤 숨긴다', () => {
    vi.useFakeTimers()
    const { container } = render(
      <BottomSheet>
        <div style={{ height: 1000 }}>내용</div>
      </BottomSheet>,
    )
    const body = container.querySelector('.sheet-body')!

    fireEvent.scroll(body)
    expect(body.classList.contains('scrollbar-visible')).toBe(true)

    act(() => vi.advanceTimersByTime(600))
    fireEvent.scroll(body)
    act(() => vi.advanceTimersByTime(600))
    expect(body.classList.contains('scrollbar-visible')).toBe(true)

    act(() => vi.advanceTimersByTime(100))
    expect(body.classList.contains('scrollbar-visible')).toBe(false)
  })

  it('언마운트할 때 대기 중인 숨김 타이머를 정리한다', () => {
    vi.useFakeTimers()
    const clearTimeout = vi.spyOn(window, 'clearTimeout')
    const { container, unmount } = render(
      <BottomSheet>
        <div>내용</div>
      </BottomSheet>,
    )
    fireEvent.scroll(container.querySelector('.sheet-body')!)

    unmount()

    expect(clearTimeout).toHaveBeenCalled()
  })
})
