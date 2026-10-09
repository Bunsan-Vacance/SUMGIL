// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BikePrediction } from '../../api/bikePrediction'
import type { BikeStock } from '../../api/contracts'
import type { Place } from '../route/types'
import BikeStationCard, { describeOutlookSlot } from './BikeStationCard'
import type { OutlookState } from './useBikeStationOutlook'

afterEach(cleanup)

const station: Place = {
  id: 'bike-station:ST-1',
  name: '강남역 1번출구',
  address: '서울',
  kind: '따릉이 대여소',
  lat: 37.5,
  lng: 127,
  dockCount: 20,
  distanceMeters: 161,
}
const stock = (overrides: Partial<BikeStock> = {}): BikeStock => ({
  rentalId: 'ST-1',
  availableBikes: 7,
  stockUpdatedAt: '2026-10-09T10:05:00+09:00',
  status: 'AVAILABLE',
  ...overrides,
})
const prediction = (overrides: Partial<BikePrediction> = {}): BikePrediction => ({
  status: 'AVAILABLE',
  predictedBikes: 4,
  availabilityProbability: 0.82,
  predictedAt: '2026-10-09T10:00:00+09:00',
  arrivalTime: '2026-10-09T10:20:00+09:00',
  rentalId: 'ST-1',
  source: 'MODEL',
  ...overrides,
})
const outlookOf = (overrides: Partial<OutlookState> = {}): OutlookState => ({
  stock: { status: 'success', value: stock() },
  predictions: {
    in15: { status: 'success', value: prediction() },
    in30: { status: 'success', value: prediction({ predictedBikes: 1 }) },
  },
  retry: vi.fn(),
  ...overrides,
})

describe('describeOutlookSlot', () => {
  it('지금 재고를 상태별로 해석한다', () => {
    const loading = describeOutlookSlot('now', outlookOf({ stock: { status: 'loading' } }), 20)
    expect(loading).toMatchObject({ title: '지금 대여 가능', message: '확인하고 있어요…' })

    expect(describeOutlookSlot('now', outlookOf(), 20)).toMatchObject({
      count: 7,
      subtitle: '10:05 갱신',
      rack: 20,
    })

    const stale = describeOutlookSlot(
      'now',
      outlookOf({ stock: { status: 'success', value: stock({ status: 'STALE' }) } }),
    )
    expect(stale).toMatchObject({
      count: 7,
      subtitle: '마지막 확인 10:05',
      note: '최신 정보가 아닐 수 있어요',
    })

    const unavailable = outlookOf({
      stock: {
        status: 'success',
        value: stock({ status: 'UNAVAILABLE', availableBikes: null, stockUpdatedAt: null }),
      },
    })
    expect(describeOutlookSlot('now', unavailable).message).toBe('지금 재고를 확인할 수 없어요')
    expect(
      describeOutlookSlot('now', outlookOf({ stock: { status: 'unavailable' } })).message,
    ).toBe('지금 재고를 확인할 수 없어요')

    expect(describeOutlookSlot('now', outlookOf({ stock: { status: 'error' } }))).toMatchObject({
      message: '재고를 불러오지 못했어요',
      error: true,
    })
  })

  it('거치대 수는 재고 응답의 rackCount를 우선한다', () => {
    const withRack = outlookOf({
      stock: { status: 'success', value: stock({ rackCount: 15 }) },
    })
    expect(describeOutlookSlot('now', withRack, 20).rack).toBe(15)
    expect(describeOutlookSlot('in15', withRack, 20).rack).toBe(20)
    expect(describeOutlookSlot('in15', withRack).rack).toBeNull()
  })

  it('예측 시점을 상태별로 해석한다', () => {
    expect(describeOutlookSlot('in15', outlookOf(), 20)).toMatchObject({
      title: '10:20 도착하면',
      subtitle: '예측 · 대여 가능성 82%',
      count: 4,
      mock: false,
    })
    const noProbability = outlookOf({
      predictions: {
        in15: {
          status: 'success',
          value: prediction({ availabilityProbability: null, source: 'MOCK' }),
        },
        in30: { status: 'unavailable' },
      },
    })
    expect(describeOutlookSlot('in15', noProbability)).toMatchObject({
      subtitle: '예측',
      mock: true,
    })
    expect(describeOutlookSlot('in30', noProbability).message).toBe('이 시점 예측이 아직 없어요')

    const unavailable = outlookOf({
      predictions: {
        in15: {
          status: 'success',
          value: prediction({ status: 'UNAVAILABLE', predictedBikes: null }),
        },
        in30: { status: 'error' },
      },
    })
    expect(describeOutlookSlot('in15', unavailable).message).toBe('이 시점 예측이 아직 없어요')
    expect(describeOutlookSlot('in30', unavailable)).toMatchObject({
      message: '예측을 불러오지 못했어요',
      error: true,
    })
  })
})

describe('대여소 카드', () => {
  const renderCard = (props: Partial<React.ComponentProps<typeof BikeStationCard>> = {}) =>
    render(
      <BikeStationCard
        station={station}
        outlook={outlookOf()}
        favorite={false}
        onToggleFavorite={vi.fn()}
        onClose={vi.fn()}
        onSetOrigin={vi.fn()}
        onSetDestination={vi.fn()}
        {...props}
      />,
    )

  it('이름·대여소 번호·거리와 재고를 보여 준다', () => {
    const { container } = renderCard()
    expect(screen.getByRole('heading', { name: '강남역 1번출구' })).toBeTruthy()
    expect(screen.getByText('따릉이 대여소 · ST-1')).toBeTruthy()
    expect(screen.getByText(/161m · 도보\s+3분/)).toBeTruthy()
    expect(container.querySelector('.bike-station-outlook-count strong')?.textContent).toBe('7대')
    expect(screen.getByText('/ 거치대 20')).toBeTruthy()
  })

  it('시점 버튼을 누르면 제목과 값이 바뀌고 샘플 예측 배지를 보여 준다', () => {
    const outlook = outlookOf({
      predictions: {
        in15: { status: 'success', value: prediction({ source: 'MOCK' }) },
        in30: { status: 'success', value: prediction({ predictedBikes: 1 }) },
      },
    })
    const { container } = renderCard({ outlook })
    fireEvent.click(screen.getByRole('button', { name: /15분 뒤/ }))
    expect(screen.getByText('10:20 도착하면')).toBeTruthy()
    expect(screen.getByText('샘플 예측')).toBeTruthy()
    expect(screen.getByRole('button', { name: /15분 뒤/ }).getAttribute('aria-pressed')).toBe(
      'true',
    )
    fireEvent.click(screen.getByRole('button', { name: /30분 뒤/ }))
    expect(container.querySelector('.bike-station-outlook-count strong')?.textContent).toBe('1대')
    expect(container.querySelector('.level-low')).not.toBeNull()
  })

  it('오류면 다시 시도 버튼이 retry를 호출한다', () => {
    const retry = vi.fn()
    renderCard({ outlook: outlookOf({ stock: { status: 'error' }, retry }) })
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('거치대 정보가 없으면 막대를 그리지 않는다', () => {
    const { container, rerender } = renderCard()
    expect(container.querySelector('.bike-station-outlook-bar')).not.toBeNull()
    rerender(
      <BikeStationCard
        station={{ ...station, dockCount: undefined }}
        outlook={outlookOf()}
        favorite={false}
        onToggleFavorite={vi.fn()}
        onClose={vi.fn()}
        onSetOrigin={vi.fn()}
        onSetDestination={vi.fn()}
      />,
    )
    expect(container.querySelector('.bike-station-outlook-bar')).toBeNull()
  })

  it('출발·도착·즐겨찾기·닫기 버튼이 각 콜백을 호출한다', () => {
    const onSetOrigin = vi.fn()
    const onSetDestination = vi.fn()
    const onToggleFavorite = vi.fn()
    const onClose = vi.fn()
    renderCard({ onSetOrigin, onSetDestination, onToggleFavorite, onClose })
    fireEvent.click(screen.getByRole('button', { name: '출발지로 설정' }))
    fireEvent.click(screen.getByRole('button', { name: '도착지로 설정' }))
    fireEvent.click(screen.getByRole('button', { name: '즐겨찾기 추가' }))
    fireEvent.click(screen.getByRole('button', { name: '대여소 정보 닫기' }))
    expect(onSetOrigin).toHaveBeenCalledWith(station)
    expect(onSetDestination).toHaveBeenCalledWith(station)
    expect(onToggleFavorite).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalledOnce()
  })
})
