// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DetailPage, { type RouteGuidanceControls } from './DetailPage'
import RouteCard from '../features/route/RouteCard'
import type { Route } from '../features/route/types'

vi.mock('../api/repositories', () => ({
  isBikePredictionMockEnabled: false,
  isBikeStockMockEnabled: false,
  bikePredictionRepository: {
    prediction: async (rentalId: string, arrivalTime: string) => ({
      rentalId,
      arrivalTime,
      status: 'AVAILABLE',
      predictedBikes: 4,
      source: 'MODEL',
    }),
  },
  bikeStockRepository: {
    stock: async (rentalId: string) => ({
      rentalId,
      status: 'AVAILABLE',
      availableBikes: rentalId === 'ST-2' ? 21 : 6,
      rackCount: 10,
      stockUpdatedAt: '2026-09-25T15:00:00+09:00',
    }),
  },
}))

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
  it('지하철 탑승·하차 버튼을 접힌 안내 조정 밖의 현재 구간에 표시한다', () => {
    const current = route('subway-confirm', 'BUS', '버스')
    const onConfirm = vi.fn()
    const guidance: RouteGuidanceControls = {
      step: 1,
      boarded: false,
      locationStatus: 'no-position',
      onConfirm,
      onExit: vi.fn(),
      onPrevious: vi.fn(),
      onNext: vi.fn(),
      onTrain: vi.fn(),
      onReplan: vi.fn(),
      replanDisabled: false,
      onRetryLocation: vi.fn(),
      onStepChange: vi.fn(),
    }
    const props = {
      selected: current,
      alternatives: [current],
      setSelectedId: vi.fn(),
      go: vi.fn(),
      startGuide: vi.fn(),
    }
    const { rerender } = render(<DetailPage {...props} guidance={guidance} />)
    const board = screen.getByRole('button', { name: '탑승했어요' })
    expect(board.closest('[aria-current="step"]')).toBeTruthy()
    expect(board.closest('details')).toBeNull()
    fireEvent.click(board)
    expect(onConfirm).toHaveBeenCalledOnce()
    rerender(<DetailPage {...props} guidance={{ ...guidance, boarded: true }} />)
    expect(screen.getByRole('button', { name: '하차했어요' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '탑승했어요' })).toBeNull()
    expect(screen.getByText('transfer에서 하차 후 확인해 주세요.')).toBeTruthy()
  })

  it('정확한 위치일 때 다음 지점 근처임을 알리고 위치 오차 시에는 경고한다', () => {
    const current = route('nearby', 'BUS', '버스')
    current.legs[0].to = { ...current.legs[0].to, lat: 37.5, lng: 127 }
    const guidance: RouteGuidanceControls = {
      step: 0,
      locationStatus: 'tracking',
      position: { latitude: 37.5001, longitude: 127, accuracy: 5 },
      onExit: vi.fn(),
      onPrevious: vi.fn(),
      onNext: vi.fn(),
      onTrain: vi.fn(),
      onReplan: vi.fn(),
      replanDisabled: false,
      onRetryLocation: vi.fn(),
      onStepChange: vi.fn(),
    }
    const props = {
      selected: current,
      alternatives: [current],
      setSelectedId: vi.fn(),
      go: vi.fn(),
      startGuide: vi.fn(),
    }
    const { rerender } = render(<DetailPage {...props} guidance={guidance} />)
    expect(screen.getByText('station 근처예요.')).toBeTruthy()
    rerender(
      <DetailPage
        {...props}
        guidance={{ ...guidance, position: null, locationStatus: 'inaccurate' }}
      />,
    )
    expect(screen.getByText(/위치 오차가 커요/)).toBeTruthy()
    expect(screen.queryByText('station 근처예요.')).toBeNull()
  })

  it('이동 시간 막대는 공유하고 검색 결과의 혼잡도만 노선 옆으로 옮긴다', () => {
    const current = route('shared-strip', 'BUS', '버스')
    current.legs[1].segmentCongestionGrade = 'CONGESTED'
    const { container } = render(
      <>
        <RouteCard route={current} onDetail={vi.fn()} />
        <DetailPage
          selected={current}
          alternatives={[current]}
          setSelectedId={vi.fn()}
          go={vi.fn()}
          startGuide={vi.fn()}
        />
      </>,
    )
    const card = container.querySelector('.route-card')!
    const detail = container.querySelector('.route-detail-summary')!
    expect(detail.querySelector('.mode-strip')?.outerHTML).toBe(
      card.querySelector('.mode-strip')?.outerHTML,
    )
    expect(detail.querySelector('.route-segment-labels')?.textContent).toContain('혼잡')
    expect(card.querySelector('.route-segment-labels')).toBeNull()
    expect(card.querySelector('.route-stop-congestion')?.textContent).toBe('혼잡')
  })

  it('같은 시트에서 안내를 시작해도 따릉이 예측을 유지하고 반납 재고는 조회하지 않는다', async () => {
    const current: Route = {
      ...route('bike', 'BUS', '버스'),
      departedAt: new Date().toISOString(),
      legs: [
        {
          mode: 'bike',
          title: '따릉이 이동',
          note: '',
          minutes: 10,
          from: { name: '대여소 A', rentalId: 'ST-1' },
          to: { name: '대여소 B', rentalId: 'ST-2' },
        },
      ],
    }
    const props = {
      selected: current,
      alternatives: [current],
      setSelectedId: vi.fn(),
      go: vi.fn(),
      startGuide: vi.fn(),
    }
    const { rerender } = render(<DetailPage {...props} />)
    await waitFor(() => expect(screen.getByText('4대 예상')).toBeTruthy())
    expect(screen.getByText('6대')).toBeTruthy()
    expect(screen.queryByText('반납 대여소 혼잡 · 현장 공간 확인 필요')).toBeNull()
    const sheet = screen.getByRole('region', { name: '경로 안내 패널' })
    fireEvent.click(screen.getByRole('button', { name: '바텀시트 펼치기' }))
    rerender(
      <DetailPage
        {...props}
        guidance={{
          step: 0,
          locationStatus: 'tracking',
          onExit: vi.fn(),
          onPrevious: vi.fn(),
          onNext: vi.fn(),
          onTrain: vi.fn(),
          onReplan: vi.fn(),
          replanDisabled: false,
          onRetryLocation: vi.fn(),
          onStepChange: vi.fn(),
        }}
      />,
    )
    expect(screen.getByRole('region', { name: '경로 안내 패널' })).toBe(sheet)
    expect(sheet.getAttribute('data-snap')).toBe('expanded')
    expect(screen.getByText('4대 예상')).toBeTruthy()
    expect(screen.getByText('6대')).toBeTruthy()
    expect(sheet.querySelector('[aria-current="step"]')).toBeTruthy()
    expect(screen.getByRole('button', { name: '안내 종료' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '다음 구간' })).toBeNull()
    expect(screen.queryByRole('button', { name: '안내 시작' })).toBeNull()
  })
  it('경로 상세의 혼잡도를 등급 글자와 색으로 표시한다', () => {
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
        selected={current}
        alternatives={[current]}
        setSelectedId={vi.fn()}
        go={vi.fn()}
        startGuide={vi.fn()}
      />,
    )

    const congestion = document.querySelector(
      '.route-detail-congestion strong[style]',
    ) as HTMLElement
    expect(congestion.textContent).toBe('혼잡')
    expect(congestion.style.color).toBe('rgb(185, 28, 28)')
    expect(congestion.closest('.route-detail-summary-top')?.querySelector('h2')).toBeTruthy()
    expect(document.querySelector('.route-detail-congestion')?.textContent).not.toContain('%')
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
        selected={current}
        alternatives={[current]}
        setSelectedId={setSelectedId}
        go={vi.fn()}
        startGuide={vi.fn()}
      />,
    )

    const region = screen.getByRole('region', { name: '이용 가능한 버스' })
    expect(region.textContent).not.toContain('transfer → destination')
    expect(screen.getByRole('list', { name: '경로 상세' }).textContent).toContain('transfer')
    expect(screen.getByRole('list', { name: '경로 상세' }).textContent).toContain('destination')
    const disclosure = region.querySelector('details')
    expect(disclosure?.open).toBe(false)
    expect(screen.getByText('이용 가능한 버스 2개 노선')).toBeTruthy()
    fireEvent.click(screen.getByText('이용 가능한 버스 2개 노선'))
    expect(disclosure?.open).toBe(true)
    expect(region.textContent).toContain('108번')
    expect(region.textContent).toContain('약 10분 간격')
    expect(region.textContent).toContain('143번')
    expect(region.textContent).not.toContain('배차 정보 없음')
    expect(region.querySelectorAll('button')).toHaveLength(0)
    expect(setSelectedId).not.toHaveBeenCalled()
  })

  it('빈 BUS leg 선택지는 노선 정보가 없다고 표시한다', () => {
    const current = route('current', 'BUS', '버스')
    current.legs[2].busRouteOptions = []

    render(
      <DetailPage
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
