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

describe('BottomSheet 스냅', () => {
  const grip = (container: HTMLElement) => container.querySelector('.sheet-grip')!

  it('손잡이 클릭은 접힘 → 기본 → 펼침 → 기본 순으로 순환한다', () => {
    const { container } = render(
      <BottomSheet initialSnap="collapsed">
        <div>내용</div>
      </BottomSheet>,
    )
    const sheet = container.querySelector('.bottom-sheet')!
    expect(sheet.getAttribute('data-snap')).toBe('collapsed')
    fireEvent.click(grip(container))
    expect(sheet.getAttribute('data-snap')).toBe('default')
    fireEvent.click(grip(container))
    expect(sheet.getAttribute('data-snap')).toBe('expanded')
    fireEvent.click(grip(container))
    expect(sheet.getAttribute('data-snap')).toBe('default')
  })

  it('children이 함수면 현재 snap과 setSnap을 받는다', () => {
    const { container } = render(
      <BottomSheet initialSnap="collapsed">
        {({ snap, setSnap }) => <button onClick={() => setSnap('expanded')}>현재 {snap}</button>}
      </BottomSheet>,
    )
    const button = container.querySelector('.sheet-body button')!
    expect(button.textContent).toBe('현재 collapsed')
    fireEvent.click(button)
    expect(container.querySelector('.bottom-sheet')!.getAttribute('data-snap')).toBe('expanded')
    expect(button.textContent).toBe('현재 expanded')
  })

  it('collapsedHeight가 드래그 최소 높이로 쓰인다', () => {
    const { container } = render(
      <BottomSheet collapsedHeight={128}>
        <div>내용</div>
      </BottomSheet>,
    )
    const sheet = container.querySelector<HTMLElement>('.bottom-sheet')!
    // jsdom에는 레이아웃이 없어 부모 높이(800)와 시트 현재 높이(300)를 직접 지정한다.
    Object.defineProperty(sheet.parentElement!, 'clientHeight', { configurable: true, value: 800 })
    sheet.getBoundingClientRect = () => ({ height: 300 }) as DOMRect
    const handle = grip(container) as HTMLElement
    handle.setPointerCapture = vi.fn()
    fireEvent.pointerDown(handle, { button: 0, clientY: 500, pointerId: 1 })
    fireEvent.pointerMove(handle, { clientY: 900, pointerId: 1 })
    expect(sheet.style.height).toBe('128px')
  })
})
