// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ArrivalPage from './ArrivalPage'

afterEach(cleanup)

const props = { destinationName: '강남역', onHome: vi.fn(), onSaveRoute: vi.fn() }

describe('도착 화면', () => {
  it('저장할 수 없으면 저장 버튼을 보여 주지 않는다', () => {
    render(<ArrivalPage {...props} canSave={false} saved={false} />)
    expect(screen.queryByRole('button', { name: /저장/ })).toBeNull()
  })

  it('이 경로 저장을 누르면 저장을 요청한다', () => {
    const onSaveRoute = vi.fn()
    render(<ArrivalPage {...props} onSaveRoute={onSaveRoute} canSave saved={false} />)
    fireEvent.click(screen.getByRole('button', { name: '이 경로 저장' }))
    expect(onSaveRoute).toHaveBeenCalledOnce()
  })

  it('저장된 경로는 저장됨으로 표시하고 비활성화한다', () => {
    render(<ArrivalPage {...props} canSave saved />)
    const button = screen.getByRole('button', { name: '저장됨' })
    expect(button.hasAttribute('disabled')).toBe(true)
    expect(button.getAttribute('aria-pressed')).toBe('true')
  })
})
