// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DetailPage from './DetailPage'
import type { Route } from '../features/route/types'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

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
  it('혼잡도 퍼센트를 소숫점 첫째 자리까지 반올림해 표시한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    const current = route('current', 'BUS', '버스')
    current.departedAt = '2026-09-17T09:00:00+09:00'
    current.congestionPrediction = {
      congestionPercent: 120.04,
      congestionGrade: 'HIGH',
      dataStatus: 'AVAILABLE',
      predictionBasis: 'RECENT_7D',
    }

    render(
      <DetailPage
        origin={{ id: 'origin', name: '출발', address: '', kind: '장소' }}
        destinationName="도착"
        selected={current}
        alternatives={[current]}
        setSelectedId={vi.fn()}
        go={vi.fn()}
        startGuide={vi.fn()}
      />,
    )

    expect(screen.getByText('120.0%')).toBeTruthy()
    expect(screen.getByText('120.0%').style.color).toBe('rgb(185, 28, 28)')
    expect(screen.getAllByText('혼잡도 예상')).toHaveLength(1)
    expect(screen.queryByText('요일 평균 기준')).toBeNull()
    expect(screen.queryByText('다른 경로')).toBeNull()
  })

  it('BUS leg 내부 노선명과 배차간격을 표시하고 경로 선택으로 취급하지 않는다', () => {
    const current = route('current', 'BUS', '버스')
    current.legs[2].busRouteOptions = [
      { routeId: '108', routeName: '108번', headwayMin: 10 },
      { routeId: '143' },
    ]
    const setSelectedId = vi.fn()

    render(
      <DetailPage
        origin={{ id: 'origin', name: '출발', address: '', kind: '장소' }}
        destinationName="도착"
        selected={current}
        alternatives={[current]}
        setSelectedId={setSelectedId}
        go={vi.fn()}
        startGuide={vi.fn()}
      />,
    )

    const region = screen.getByRole('region', { name: '이용 가능한 버스' })
    expect(region.textContent).toContain('transfer → destination')
    expect(region.textContent).toContain('108번')
    expect(region.textContent).toContain('약 10분 간격')
    expect(region.textContent).toContain('143번')
    expect(region.textContent).toContain('배차 정보 없음')
    expect(region.querySelectorAll('button')).toHaveLength(0)
    expect(setSelectedId).not.toHaveBeenCalled()
  })

  it('빈 BUS leg 선택지는 노선 정보가 없다고 표시한다', () => {
    const current = route('current', 'BUS', '버스')
    current.legs[2].busRouteOptions = []

    render(
      <DetailPage
        origin={{ id: 'origin', name: '출발', address: '', kind: '장소' }}
        destinationName="도착"
        selected={current}
        alternatives={[current]}
        setSelectedId={vi.fn()}
        go={vi.fn()}
        startGuide={vi.fn()}
      />,
    )

    expect(screen.getByText('버스 노선 정보를 확인하지 못했어요.')).toBeTruthy()
  })

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
