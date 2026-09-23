// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import RouteCard from './RouteCard'
import type { Route } from './types'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

function route(overrides: Partial<Route> = {}): Route {
  return {
    id: 'route',
    label: '빠른 경로',
    minutes: 15,
    transfers: 1,
    source: 'MOCK',
    modes: ['subway'],
    departedAt: '2026-09-17T09:00:00+09:00',
    congestionPrediction: {
      congestionPercent: 68,
      congestionGrade: 'MEDIUM',
      dataStatus: 'AVAILABLE',
      predictionBasis: 'RECENT_7D',
    },
    legs: [
      {
        mode: 'subway',
        title: '역삼역 → 선릉역',
        note: '2호선',
        minutes: 15,
      },
    ],
    ...overrides,
  }
}

describe('경로 카드 구간 혼잡도', () => {
  it('최근 7일 근거 문구 없이 우측 요약에 등급만 표시한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    render(<RouteCard route={route()} onDetail={vi.fn()} />)

    const prediction = document.querySelector('.route-card-prediction')
    expect(prediction?.textContent).toContain('혼잡도 예상')
    expect(prediction?.textContent).not.toContain('%')
    expect(prediction?.textContent).toContain('보통')
    expect(screen.queryByText('최근 7일 데이터 기반')).toBeNull()
  })

  it('샘플 경로에만 샘플 표식을 표시하고 실제 경로 정보 문구는 표시하지 않는다', () => {
    const { rerender } = render(<RouteCard route={route()} onDetail={vi.fn()} />)

    expect(screen.getByText('샘플')).toBeTruthy()
    expect(screen.queryByText('경로 정보')).toBeNull()

    rerender(<RouteCard route={route({ source: 'ALGORITHM' })} onDetail={vi.fn()} />)

    expect(screen.queryByText('샘플')).toBeNull()
    expect(screen.queryByText('경로 정보')).toBeNull()
  })

  it('예측이 없으면 우측 요약에 예측 정보 없음을 표시한다', () => {
    render(
      <RouteCard
        route={route({ source: 'ALGORITHM', congestionPrediction: undefined })}
        onDetail={vi.fn()}
      />,
    )

    expect(document.querySelector('.route-card-prediction')?.textContent).toContain(
      '예측 정보 없음',
    )
    expect(screen.getByRole('button', { name: /예측 정보 없음/ })).toBeTruthy()
  })

  it('혼잡도 수치는 화면과 접근성 라벨에서 등급 글자로 표시한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    render(
      <RouteCard
        route={route({
          congestionPrediction: {
            congestionPercent: 68.26,
            congestionGrade: 'HIGH',
            dataStatus: 'AVAILABLE',
            predictionBasis: 'RECENT_7D',
          },
        })}
        onDetail={vi.fn()}
      />,
    )

    expect(document.querySelector('.route-card-prediction')?.textContent).toContain('혼잡')
    expect(document.querySelector('.route-card-prediction')?.textContent).not.toContain('%')
    expect(screen.getByRole('button').getAttribute('aria-label')).toContain('혼잡도 예상 혼잡')
    expect(screen.getByRole('button').getAttribute('aria-label')).not.toContain('%')
  })

  it('전체 혼잡도 등급 글자에 서버 등급 색상을 적용한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    render(
      <RouteCard
        route={route({
          congestionPrediction: {
            congestionPercent: 20,
            congestionGrade: 'HIGH',
            dataStatus: 'AVAILABLE',
            predictionBasis: 'RECENT_7D',
          },
        })}
        onDetail={vi.fn()}
      />,
    )

    expect(
      (document.querySelector('.route-card-prediction strong') as HTMLElement)?.style.color,
    ).toBe('rgb(185, 28, 28)')
    expect(document.querySelector('.route-card-prediction')?.textContent).toContain('혼잡')
  })

  it('시간 아래에 경로 막대기를 바로 표시하고 경로 요약 문구는 표시하지 않는다', () => {
    const card = render(
      <RouteCard
        route={route({
          totalDistanceMeters: 2269,
          transfers: 1,
          legs: [
            { mode: 'walk', title: '출발지 → 역삼역', note: '도보', minutes: 1 },
            { mode: 'subway', title: '역삼역 → 선릉역', note: '2호선', minutes: 13 },
            { mode: 'walk', title: '선릉역 → 도착지', note: '도보', minutes: 1 },
          ],
        })}
        onDetail={vi.fn()}
      />,
    ).container.querySelector('.route-card')

    expect(card?.querySelector('.route-facts')).toBeNull()
    expect(card?.textContent).not.toContain('총 2,269m')
    expect(card?.textContent).not.toContain('환승 1회')
    expect(card?.textContent).not.toContain('도보 2분')
    expect(card?.querySelector('.route-card-main')?.nextElementSibling).toBe(
      card?.querySelector('.mode-strip'),
    )
  })

  it('모든 표시 구간을 같은 폭으로 정렬하고 등급 없는 구간은 비워 둔다', () => {
    const route: Route = {
      id: 'route',
      label: '빠른 경로',
      minutes: 10,
      transfers: 1,
      modes: ['subway'],
      legs: [
        {
          mode: 'subway',
          title: '2호선',
          note: '2호선',
          minutes: 5,
          segmentCongestionLevel: 80,
          from: { name: '역삼역' },
          to: { name: '선릉역' },
        },
        {
          mode: 'walk',
          transfer: true,
          title: '환승',
          note: '환승',
          minutes: 1,
        },
        {
          mode: 'subway',
          title: '수인분당선',
          note: '수인분당선',
          minutes: 4,
          segmentCongestionLevel: 110,
          from: { name: '선릉역' },
          to: { name: '도곡역' },
        },
      ],
    }

    render(<RouteCard route={route} onDetail={vi.fn()} />)

    const labels = screen.getByLabelText('구간별 혼잡도')
    expect(labels.children).toHaveLength(3)
    expect(Array.from(labels.children, (cell) => cell.textContent)).toEqual(['혼잡', '', '포화'])
    expect(Array.from(labels.children, (cell) => (cell as HTMLElement).style.flexGrow)).toEqual([
      '5',
      '1',
      '4',
    ])
    expect(screen.queryByText('역삼역 → 선릉역')).toBeNull()
    expect(screen.queryByText('선릉역 → 도곡역')).toBeNull()
    expect(screen.getByRole('button').getAttribute('aria-label')).toContain('상세 경로')
  })

  it('서버 구간 등급을 숫자 기반 등급보다 우선해 표시한다', () => {
    render(
      <RouteCard
        route={route({
          legs: [
            {
              mode: 'bus',
              title: '정류장 A → 정류장 B',
              note: '버스',
              minutes: 15,
              segmentCongestionLevel: 80,
              segmentCongestionGrade: 'NORMAL',
            },
          ],
        })}
        onDetail={vi.fn()}
      />,
    )

    expect(
      Array.from(screen.getByLabelText('구간별 혼잡도').children, (cell) => cell.textContent),
    ).toEqual(['보통'])
  })

  it('구간 혼잡도 값이 없으면 구간별 혼잡도 UI를 만들지 않는다', () => {
    const route: Route = {
      id: 'live-route',
      label: '실시간 경로',
      minutes: 4,
      transfers: 0,
      modes: ['subway'],
      legs: [{ mode: 'subway', title: 'B → C', note: '지하철', minutes: 4 }],
    }

    render(<RouteCard route={route} onDetail={vi.fn()} />)

    expect(screen.queryByLabelText('구간별 혼잡도')).toBeNull()
  })
})
