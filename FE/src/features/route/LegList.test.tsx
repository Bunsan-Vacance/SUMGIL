// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Route } from './types'
import LegList from './LegList'

describe('구간 이동 안내', () => {
  it('구간 거리와 혼잡도 미제공 상태를 함께 표시한다', () => {
    const route: Route = {
      id: 'route',
      label: '빠른 경로',
      minutes: 8,
      transfers: 0,
      modes: ['walk', 'subway'],
      legs: [
        { mode: 'walk', title: '출발지 → 역삼역', note: '도보', minutes: 2 },
        {
          mode: 'subway',
          title: '역삼역 → 선릉역',
          note: '2호선',
          minutes: 6,
          distanceMeters: 1234,
          from: { id: '221', name: '역삼역' },
        },
      ],
    }

    render(<LegList route={route} />)

    expect(screen.getByText('도보 · 거리 준비중입니다')).toBeTruthy()
    expect(screen.getByText('2호선 · 1.2km · 출발역 통계: 예측 정보 없음')).toBeTruthy()
  })

  it('원본 구간 인덱스의 현재 단계에 aria-current와 텍스트를 표시한다', () => {
    const route: Route = {
      id: 'route',
      label: '빠른 경로',
      minutes: 4,
      transfers: 0,
      modes: ['walk'],
      legs: [
        { mode: 'walk', title: '출발지 → 역', note: '도보', minutes: 2 },
        { mode: 'walk', title: '역 → 도착지', note: '도보', minutes: 2 },
      ],
    }

    render(<LegList route={route} activeIndex={1} />)

    const activeItem = screen.getByText('현재 단계').parentElement?.parentElement?.parentElement
    expect(activeItem?.getAttribute('aria-current')).toBe('step')
    expect(activeItem?.classList.contains('is-active')).toBe(true)
  })
})
