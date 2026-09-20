// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { Route } from './types'
import LegList, { compactLegs } from './LegList'

afterEach(cleanup)

describe('구간 이동 안내', () => {
  it('실제 구간 혼잡도 숫자와 거리를 함께 표시한다', () => {
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
          segmentCongestionLevel: 20,
          from: { id: '221', name: '역삼역' },
        },
      ],
    }

    render(<LegList route={route} />)

    expect(screen.getByText('도보 · 거리 준비중입니다')).toBeTruthy()
    expect(screen.getByText('2호선 · 1.2km · 구간 예상 혼잡도 20%')).toBeTruthy()
  })

  it('구간 혼잡도 값이 없으면 혼잡도 숫자를 표시하지 않는다', () => {
    const route: Route = {
      id: 'route-without-congestion',
      label: '빠른 경로',
      minutes: 4,
      transfers: 0,
      modes: ['subway'],
      legs: [{ mode: 'subway', title: '역삼역 → 선릉역', note: '2호선', minutes: 4 }],
    }

    render(<LegList route={route} />)

    expect(screen.queryByText(/구간 예상 혼잡도/)).toBeNull()
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

  it('선택 가능한 버스 노선 목록이 다른 연속 구간은 합치지 않는다', () => {
    const legs = [
      {
        mode: 'bus' as const,
        title: '정류장 A → 정류장 B',
        note: '버스',
        routeId: 'BUS',
        minutes: 3,
        busRouteOptions: [{ routeId: '108' }],
      },
      {
        mode: 'bus' as const,
        title: '정류장 B → 정류장 C',
        note: '버스',
        routeId: 'BUS',
        minutes: 4,
        busRouteOptions: [{ routeId: '143' }],
      },
    ]

    expect(compactLegs(legs)).toHaveLength(2)
  })
})
