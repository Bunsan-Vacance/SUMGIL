import { describe, expect, it } from 'vitest'
import { feedbackCardView } from './feedbackCard'
import type { FeedbackTarget } from './congestionFeedback'

const target = (overrides: Partial<FeedbackTarget['leg']>, boardedAt?: string): FeedbackTarget => ({
  index: 0,
  boardedAt,
  leg: { mode: 'subway', title: '2호선', note: '', minutes: 10, ...overrides },
})

describe('혼잡 체감 피드백 카드 표시', () => {
  it('지하철 제목과 구간·탑승 시각 부제, 노선 배지를 만든다', () => {
    const view = feedbackCardView(
      target(
        { routeId: '1002', from: { name: '강남' }, to: { name: '당산' } },
        '2026-09-17T09:42:00.000Z',
      ),
    )
    expect(view.title).toBe('지하철, 실제로 붐볐나요?')
    // Asia/Seoul 기준
    expect(view.subtitle).toBe('강남 → 당산 · 18:42 탑승')
    expect(view.line).toMatchObject({ label: '2', background: '#00A84D' })
    expect(view.options.map((option) => option.label)).toEqual(['여유', '보통', '혼잡'])
    expect(view.options[2].color).toBe('#b91c1c')
  })

  it('탑승 시각을 모르면 시각을 뺀다', () => {
    expect(
      feedbackCardView(target({ from: { name: '강남' }, to: { name: '당산' } })).subtitle,
    ).toBe('강남 → 당산')
  })

  it('버스는 버스 제목이고 노선 배지가 없다', () => {
    const view = feedbackCardView(target({ mode: 'bus', title: '146' }))
    expect(view.title).toBe('버스, 실제로 붐볐나요?')
    expect(view.line).toBeUndefined()
  })
})
