// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { tabToLayer, useHomeTab } from './useHomeTab'

describe('useHomeTab', () => {
  it('탭은 null로 시작하고 setTab으로 바뀐다', () => {
    const { result } = renderHook(() => useHomeTab(true))
    expect(result.current.tab).toBeNull()
    act(() => result.current.setTab('bike'))
    expect(result.current.tab).toBe('bike')
  })

  it('홈을 벗어나면 탭을 해제한다', () => {
    const { result, rerender } = renderHook(({ active }) => useHomeTab(active), {
      initialProps: { active: true },
    })
    act(() => result.current.setTab('crowd'))
    rerender({ active: false })
    expect(result.current.tab).toBeNull()
  })

  it('탭에서 레이어를 파생한다', () => {
    expect(tabToLayer('crowd')).toBe('crowd')
    expect(tabToLayer('bike')).toBe('bike')
    expect(tabToLayer('recent')).toBeNull()
    expect(tabToLayer(null)).toBeNull()
  })
})
