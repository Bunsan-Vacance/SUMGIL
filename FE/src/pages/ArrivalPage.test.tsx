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

describe('도착 화면 혼잡 체감 카드', () => {
  const target = {
    index: 0,
    boardedAt: '2026-09-17T09:42:00.000Z',
    leg: {
      mode: 'subway' as const,
      title: '2호선',
      note: '',
      minutes: 10,
      routeId: '1002',
      from: { name: '강남' },
      to: { name: '당산' },
    },
  }

  it('대상 구간이 없으면 카드를 그리지 않는다', () => {
    render(<ArrivalPage {...props} canSave={false} saved={false} feedbackTarget={null} />)
    expect(screen.queryByRole('group', { name: '실제 혼잡도' })).toBeNull()
  })

  it('등급을 고르면 onFeedback을 부른다', () => {
    const onFeedback = vi.fn()
    render(
      <ArrivalPage
        {...props}
        canSave={false}
        saved={false}
        feedbackTarget={target}
        onFeedback={onFeedback}
      />,
    )
    expect(screen.getByText('지하철, 실제로 붐볐나요?')).toBeTruthy()
    expect(screen.getByText(/강남 → 당산 · 18:42 탑승/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /혼잡/ }))
    expect(onFeedback).toHaveBeenCalledWith('CONGESTED')
  })

  it('보낸 뒤에는 선택 결과만 보여 주고 버튼을 없앤다', () => {
    render(
      <ArrivalPage
        {...props}
        canSave={false}
        saved={false}
        feedbackTarget={target}
        feedbackGrade="CONGESTED"
        onFeedback={vi.fn()}
      />,
    )
    expect(screen.getByRole('status').textContent).toContain("'혼잡'으로 알려주셨어요")
    expect(screen.getByText('다음 혼잡도 예측에 참고할게요')).toBeTruthy()
    expect(screen.queryByRole('group', { name: '실제 혼잡도' })).toBeNull()
  })

  it('버스 구간이면 버스 제목을 쓴다', () => {
    render(
      <ArrivalPage
        {...props}
        canSave={false}
        saved={false}
        feedbackTarget={{ ...target, leg: { ...target.leg, mode: 'bus' as const } }}
        onFeedback={vi.fn()}
      />,
    )
    expect(screen.getByText('버스, 실제로 붐볐나요?')).toBeTruthy()
  })
})
