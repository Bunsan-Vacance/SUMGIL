// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import DepartureTimeDialog from './DepartureTimeDialog'

afterEach(cleanup)

beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value() {
      this.setAttribute('open', '')
    },
  })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value() {
      this.removeAttribute('open')
    },
  })
})

afterAll(() => {
  vi.restoreAllMocks()
})

describe('출발 시간 선택', () => {
  it('초기 시각을 맞춰 보여주고 키보드와 클릭 선택을 적용한다', () => {
    const onApply = vi.fn()
    const onClose = vi.fn()
    render(<DepartureTimeDialog initialValue="13:27" onApply={onApply} onClose={onClose} />)

    const hours = screen.getByRole('listbox', { name: '시 선택' })
    const minutes = screen.getByRole('listbox', { name: '분 선택' })
    expect(within(hours).getByRole('option', { name: '13', selected: true })).toBeTruthy()
    expect(within(minutes).getByRole('option', { name: '27', selected: true })).toBeTruthy()

    fireEvent.keyDown(hours, { key: 'ArrowUp' })
    fireEvent.click(within(minutes).getByRole('option', { name: '42' }))
    fireEvent.click(screen.getByRole('button', { name: '적용' }))

    expect(onApply).toHaveBeenCalledWith('12:42')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('취소하면 선택값을 적용하지 않고 닫기를 요청한다', () => {
    const onApply = vi.fn()
    const onClose = vi.fn()
    render(<DepartureTimeDialog initialValue="09:00" onApply={onApply} onClose={onClose} />)

    fireEvent.keyDown(screen.getByRole('listbox', { name: '분 선택' }), { key: 'ArrowDown' })
    fireEvent.click(screen.getByRole('button', { name: '취소' }))

    expect(onApply).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledOnce()
  })
})
