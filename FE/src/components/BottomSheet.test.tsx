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

describe('BottomSheet 끌어 내려 닫기', () => {
  // jsdom에는 레이아웃이 없어 부모 높이(800)와 시트 현재 높이를 직접 지정한다.
  function setup(snap: 'default' | 'expanded', height: number, onDismiss = vi.fn()) {
    const { container, rerender } = render(
      <BottomSheet initialSnap={snap} onDismiss={onDismiss}>
        <div>내용</div>
      </BottomSheet>,
    )
    const sheet = container.querySelector<HTMLElement>('.bottom-sheet')!
    Object.defineProperty(sheet.parentElement!, 'clientHeight', { configurable: true, value: 800 })
    sheet.getBoundingClientRect = () => ({ height }) as DOMRect
    const handle = container.querySelector<HTMLElement>('.sheet-grip')!
    handle.setPointerCapture = vi.fn()
    const dragDown = (distance: number) => {
      fireEvent.pointerDown(handle, { button: 0, clientY: 100, pointerId: 1 })
      fireEvent.pointerMove(handle, { clientY: 100 + distance, pointerId: 1 })
      fireEvent.pointerUp(handle, { clientY: 100 + distance, pointerId: 1 })
    }
    return { sheet, onDismiss, dragDown, rerender }
  }

  it('기본 높이의 60%를 아래로 끌어 놓으면 닫히고 onDismiss를 한 번 부른다', () => {
    const { sheet, onDismiss, dragDown } = setup('default', 300)
    dragDown(180)
    expect(sheet.getAttribute('data-snap')).toBe('closed')
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('기본 높이의 40%만 끌어 내리면 기본 높이를 유지하고 onDismiss를 부르지 않는다', () => {
    const { sheet, onDismiss, dragDown } = setup('default', 300)
    dragDown(120)
    expect(sheet.getAttribute('data-snap')).toBe('default')
    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('펼침에서 크게 내리면 기본 높이로만 내려가고 닫히지 않는다', () => {
    const { sheet, onDismiss, dragDown } = setup('expanded', 750)
    dragDown(600)
    expect(sheet.getAttribute('data-snap')).toBe('default')
    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('닫힘 상태에서 preferredSnap이 default로 바뀌면 다시 열린다', () => {
    const { container, rerender } = render(
      <BottomSheet initialSnap="closed" preferredSnap="closed">
        <div>내용</div>
      </BottomSheet>,
    )
    const sheet = container.querySelector('.bottom-sheet')!
    expect(sheet.getAttribute('data-snap')).toBe('closed')
    rerender(
      <BottomSheet initialSnap="closed" preferredSnap="default">
        <div>내용</div>
      </BottomSheet>,
    )
    expect(sheet.getAttribute('data-snap')).toBe('default')
    expect(sheet.getAttribute('aria-hidden')).toBeNull()
  })

  it('닫힘이면 aria-hidden이고 손잡이는 탭 순서에서 빠진다', () => {
    const { container } = render(
      <BottomSheet initialSnap="closed">
        <div>내용</div>
      </BottomSheet>,
    )
    expect(container.querySelector('.bottom-sheet')!.getAttribute('aria-hidden')).toBe('true')
    expect(container.querySelector('.sheet-grip')!.getAttribute('tabindex')).toBe('-1')
  })
})
