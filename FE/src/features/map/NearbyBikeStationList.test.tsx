// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BikeStation } from './bikeStations'
import NearbyBikeStationList from './NearbyBikeStationList'

afterEach(cleanup)

const station = (overrides: Partial<BikeStation>): BikeStation => ({
  id: 'ST-1',
  name: '101. 강남역 1번출구',
  address: '서울',
  lat: 37.5,
  lng: 127,
  ...overrides,
})

const rows = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('.nearby-station-list > li'))

describe('주변 따릉이 목록', () => {
  it('제목과 재고 범례를 보여 준다', () => {
    const { container } = render(<NearbyBikeStationList stations={[]} onSelect={vi.fn()} />)
    expect(screen.getByRole('heading', { name: '주변 따릉이' })).toBeTruthy()
    expect(screen.getByText('가까운 순')).toBeTruthy()
    const legend = container.querySelector('.home-layer-legend')!
    expect(legend.textContent).toContain('3대 이상')
    expect(legend.textContent).toContain('2대 이하')
  })

  it('가까운 순으로 정렬하고 거리가 없는 항목은 뒤로 보낸다', () => {
    const { container } = render(
      <NearbyBikeStationList
        stations={[
          station({ id: 'none', name: '102. 거리없음' }),
          station({ id: 'far', name: '103. 먼곳', distanceMeters: 1500 }),
          station({ id: 'near', name: '104. 가까운곳', distanceMeters: 120.4 }),
        ]}
        onSelect={vi.fn()}
      />,
    )
    expect(rows(container).map((row) => row.querySelector('strong')?.textContent)).toEqual([
      '104. 가까운곳',
      '103. 먼곳',
      '102. 거리없음',
    ])
  })

  it('최대 20개만 보여 준다', () => {
    const stations = Array.from({ length: 25 }, (_, index) =>
      station({ id: `ST-${index}`, name: `${index}. 역${index}`, distanceMeters: index * 10 }),
    )
    const { container } = render(<NearbyBikeStationList stations={stations} onSelect={vi.fn()} />)
    expect(rows(container)).toHaveLength(20)
  })

  it('배지에 재고 숫자와 색 규칙을 적용하고 알 수 없으면 회색 물음표를 보여 준다', () => {
    const { container } = render(
      <NearbyBikeStationList
        stations={[
          station({ id: 'a', distanceMeters: 10, availableBikes: 5 }),
          station({ id: 'b', distanceMeters: 20, availableBikes: 2 }),
          station({ id: 'c', distanceMeters: 30, availableBikes: null }),
          station({ id: 'd', distanceMeters: 40 }),
        ]}
        onSelect={vi.fn()}
      />,
    )
    const badges = rows(container).map((row) => row.querySelector('.nearby-bike-badge')!)
    expect(badges.map((badge) => badge.textContent)).toEqual(['5', '2', '?', '?'])
    expect(badges.map((badge) => badge.className)).toEqual([
      'nearby-bike-badge level-ok',
      'nearby-bike-badge level-low',
      'nearby-bike-badge level-unknown',
      'nearby-bike-badge level-unknown',
    ])
  })

  it('있는 부가 정보만 보여 주고 없는 값은 생략한다', () => {
    const { container } = render(
      <NearbyBikeStationList
        stations={[
          station({ id: 'a', distanceMeters: 10, availableBikes: 5, dockCount: 15 }),
          station({ id: 'b', distanceMeters: 1240 }),
          station({ id: 'c', distanceMeters: 2000 }),
        ]}
        onSelect={vi.fn()}
      />,
    )
    const details = rows(container).map((row) => row.querySelector('small')?.textContent)
    expect(details[0]).toBe('대여 가능 5대 · 거치대 15 · 10m')
    expect(details[1]).toBe('1.2km')
    const bare = render(
      <NearbyBikeStationList stations={[station({ id: 'z' })]} onSelect={vi.fn()} />,
    )
    expect(bare.container.querySelector('.nearby-station-list small')).toBeNull()
  })

  it('행을 누르면 해당 대여소로 onSelect를 호출한다', () => {
    const onSelect = vi.fn()
    const target = station({ id: 'ST-9', name: '109. 시험 대여소', distanceMeters: 50 })
    render(<NearbyBikeStationList stations={[target]} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: /시험 대여소/ }))
    expect(onSelect).toHaveBeenCalledWith(target)
  })

  it('비어 있으면 안내 문구를 보여 준다', () => {
    render(<NearbyBikeStationList stations={[]} onSelect={vi.fn()} />)
    expect(screen.getByText('주변에 대여소가 없어요')).toBeTruthy()
  })
})
