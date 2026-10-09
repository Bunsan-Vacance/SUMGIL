// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import NearbyStationList from './NearbyStationList'
import type { StationCongestion } from './useNearbyStationCongestion'

afterEach(cleanup)

const station = (overrides: Partial<StationCongestion>): StationCongestion => ({
  stationId: '1',
  stationName: '역',
  lat: 37.5,
  lng: 127,
  distanceMeters: 100,
  lines: [{ lineId: '1002', lineName: '2호선' }],
  level: null,
  grade: null,
  updatedAt: null,
  ...overrides,
})

const stations = [
  station({ stationId: 'far', stationName: '먼역', distanceMeters: 1240, grade: 'SATURATED' }),
  station({
    stationId: 'near',
    stationName: '가까운역',
    distanceMeters: 320.4,
    grade: 'RELAXED',
    lines: [
      { lineId: '1002', lineName: '2호선' },
      { lineId: '1009', lineName: null },
    ],
  }),
  station({ stationId: 'none', stationName: '정보없는역', distanceMeters: 800, grade: null }),
]

function setup(props: Partial<React.ComponentProps<typeof NearbyStationList>> = {}) {
  const onSelect = vi.fn()
  const onRetry = vi.fn()
  const rendered = render(
    <NearbyStationList
      stations={stations}
      status="ready"
      onSelect={onSelect}
      onRetry={onRetry}
      {...props}
    />,
  )
  return { ...rendered, onSelect, onRetry }
}

describe('주변 역 목록', () => {
  it('제목과 범례 5개를 보여 준다', () => {
    const { container } = setup()
    expect(screen.getByRole('heading', { name: '주변 역 혼잡도' })).toBeTruthy()
    expect(screen.getByText('가까운 순 · 1.5km')).toBeTruthy()
    const legend = container.querySelector('.home-layer-legend')!
    expect(Array.from(legend.querySelectorAll('span')).map((item) => item.textContent)).toEqual([
      '여유',
      '보통',
      '혼잡',
      '포화',
      '정보 없음',
    ])
  })

  it('가까운 순으로 정렬하고 거리를 m·km로 표기한다', () => {
    const { container } = setup()
    const rows = Array.from(container.querySelectorAll('.nearby-station-list > li'))
    expect(rows.map((row) => row.querySelector('strong')?.textContent)).toEqual([
      '가까운역',
      '정보없는역',
      '먼역',
    ])
    expect(rows[0].textContent).toContain('2호선 · 1009 · 320m')
    expect(rows[1].textContent).toContain('800m')
    expect(rows[2].textContent).toContain('1.2km')
  })

  it('등급 라벨과 색을 보여 주고 등급이 없으면 정보 없음 회색이다', () => {
    const { container } = setup()
    const rows = Array.from(container.querySelectorAll('.nearby-station-list > li'))
    expect(rows[0].textContent).toContain('여유')
    expect((rows[0].querySelector('.nearby-station-grade') as HTMLElement).style.background).toBe(
      'rgb(29, 78, 216)',
    )
    expect(rows[1].textContent).toContain('정보 없음')
    expect((rows[1].querySelector('.nearby-station-grade') as HTMLElement).style.background).toBe(
      'rgb(130, 144, 155)',
    )
    expect(rows[2].textContent).toContain('포화')
  })

  it('행을 누르면 해당 역으로 onSelect를 호출한다', () => {
    const { onSelect } = setup()
    fireEvent.click(screen.getByRole('button', { name: /가까운역/ }))
    expect(onSelect).toHaveBeenCalledWith(stations[1])
  })

  it('조회 중에는 안내 문구, 비어 있으면 빈 목록 문구를 보여 준다', () => {
    const { rerender, onSelect, onRetry } = setup({ stations: [], status: 'loading' })
    expect(screen.getByText(/주변 역을 찾고 있어요/)).toBeTruthy()
    rerender(
      <NearbyStationList stations={[]} status="idle" onSelect={onSelect} onRetry={onRetry} />,
    )
    expect(screen.getByText(/주변 역을 찾고 있어요/)).toBeTruthy()
    rerender(
      <NearbyStationList stations={[]} status="ready" onSelect={onSelect} onRetry={onRetry} />,
    )
    expect(screen.getByText('주변 1.5km에 역이 없어요')).toBeTruthy()
  })

  it('조회 실패 시 안내와 다시 시도 버튼을 보여 주고 누르면 onRetry를 호출한다', () => {
    const { onRetry } = setup({ stations: [], status: 'error' })
    expect(screen.getByText('주변 역을 불러오지 못했어요')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
