// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import HomeLayerToggle from './HomeLayerToggle'

afterEach(cleanup)

describe('홈 지도 레이어 토글', () => {
  it('레이어가 없으면 아무것도 렌더링하지 않는다', () => {
    const { container } = render(<HomeLayerToggle layers={[]} active={null} onChange={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('켜진 버튼을 다시 누르면 null로 끄고 다른 버튼은 교체한다', () => {
    const onChange = vi.fn()
    render(<HomeLayerToggle layers={['crowd', 'bike']} active="bike" onChange={onChange} />)
    expect(screen.getByRole('button', { name: '따릉이 레이어' }).getAttribute('aria-pressed')).toBe(
      'true',
    )
    fireEvent.click(screen.getByRole('button', { name: '따릉이 레이어' }))
    expect(onChange).toHaveBeenLastCalledWith(null)
    fireEvent.click(screen.getByRole('button', { name: '혼잡도 레이어' }))
    expect(onChange).toHaveBeenLastCalledWith('crowd')
  })
})
