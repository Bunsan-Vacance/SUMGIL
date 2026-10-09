// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import HomeTabBar from './HomeTabBar'

afterEach(cleanup)

describe('HomeTabBar', () => {
  it('최근기록·혼잡도·자전거 버튼을 순서대로 보여 주고 활성 탭만 눌림 상태다', () => {
    render(<HomeTabBar active="crowd" onChange={vi.fn()} />)
    const nav = screen.getByRole('navigation', { name: '홈 하단 탭' })
    const buttons = Array.from(nav.querySelectorAll('button'))
    expect(buttons.map((button) => button.textContent)).toEqual(['최근기록', '혼잡도', '자전거'])
    expect(buttons.map((button) => button.getAttribute('aria-pressed'))).toEqual([
      'false',
      'true',
      'false',
    ])
  })

  it('다른 탭을 누르면 그 탭을, 활성 탭을 다시 누르면 null을 알린다', () => {
    const onChange = vi.fn()
    render(<HomeTabBar active="bike" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: '최근기록' }))
    expect(onChange).toHaveBeenLastCalledWith('recent')
    fireEvent.click(screen.getByRole('button', { name: '자전거' }))
    expect(onChange).toHaveBeenLastCalledWith(null)
  })

  it('disabled에 든 탭은 비활성이라 누를 수 없다', () => {
    const onChange = vi.fn()
    render(<HomeTabBar active={null} onChange={onChange} disabled={['crowd']} />)
    const crowd = screen.getByRole('button', { name: '혼잡도' }) as HTMLButtonElement
    expect(crowd.disabled).toBe(true)
    fireEvent.click(crowd)
    expect(onChange).not.toHaveBeenCalled()
    expect((screen.getByRole('button', { name: '자전거' }) as HTMLButtonElement).disabled).toBe(
      false,
    )
  })
})
