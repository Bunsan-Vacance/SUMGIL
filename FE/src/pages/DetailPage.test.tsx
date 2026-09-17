// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DetailPage from './DetailPage'
import type { Route } from '../features/route/types'

afterEach(cleanup)

const endpoint = (id: string, name = id) => ({ id, name })
function route(id: string, busId: string, busName: string): Route {
  return {
    id,
    label: '다른 경로',
    minutes: 20,
    transfers: 1,
    modes: ['walk', 'subway', 'bus'],
    legs: [
      {
        mode: 'walk',
        title: '출발 → 역',
        note: '도보',
        minutes: 2,
        from: endpoint('origin'),
        to: endpoint('station'),
      },
      {
        mode: 'subway',
        title: '역 → 환승역',
        note: '2호선',
        routeId: '1002',
        minutes: 8,
        from: endpoint('station'),
        to: endpoint('transfer'),
      },
      {
        mode: 'bus',
        title: '환승역 → 도착',
        note: busName,
        routeId: busId,
        minutes: 10,
        from: endpoint('transfer'),
        to: endpoint('destination'),
      },
    ],
  }
}

describe('경로 상세 버스 선택', () => {
  it('그룹화된 버스 번호를 보여주고 실제 Route를 선택한다', () => {
    const first = route('first', '420-id', '420')
    const second = route('second', 'N26-id', 'N26')
    const setSelectedId = vi.fn()
    render(
      <DetailPage
        origin={{ id: 'origin', name: '출발', address: '', kind: '장소' }}
        destinationName="도착"
        selected={first}
        alternatives={[first, second]}
        setSelectedId={setSelectedId}
        go={vi.fn()}
        startGuide={vi.fn()}
      />,
    )

    expect(screen.getByRole('region', { name: '버스 선택' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /N26/ }))
    expect(setSelectedId).toHaveBeenCalledWith('second')
  })
})
