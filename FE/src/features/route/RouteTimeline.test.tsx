// @vitest-environment jsdom

import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Route } from './types'
import RouteTimeline from './RouteTimeline'

afterEach(cleanup)

function route(legs: Route['legs']): Route {
  return {
    id: 'timeline',
    label: '빠른 경로',
    minutes: legs.reduce((sum, leg) => sum + leg.minutes, 0),
    transfers: 0,
    modes: [...new Set(legs.map((leg) => leg.mode))],
    legs,
  }
}

describe('경로 상세 타임라인', () => {
  it('안내 시작 시 스크롤을 보존하고 다음 구간 전환 때 시트 내부만 이동한다', () => {
    const value = route([
      { mode: 'walk', title: '역으로', note: '', minutes: 2 },
      { mode: 'subway', title: '지하철', note: '', minutes: 3 },
    ])
    const view = (activeIndex?: number) => (
      <div className="sheet-body">
        <RouteTimeline route={value} activeIndex={activeIndex} />
      </div>
    )
    const { container, rerender } = render(view())
    const body = container.querySelector<HTMLElement>('.sheet-body')!
    const scrollTo = vi.fn()
    body.scrollTo = scrollTo
    rerender(view(0))
    expect(scrollTo).not.toHaveBeenCalled()
    rerender(view(1))
    expect(scrollTo).toHaveBeenCalledOnce()
    expect(body.querySelector('[aria-current="step"]')?.textContent).toContain('지하철')
    rerender(view(1))
    expect(scrollTo).toHaveBeenCalledOnce()
  })

  it('도보 구간은 별도 승하차 노드가 없으므로 실제 이동 지점을 보존한다', () => {
    const value = route([
      { mode: 'walk', title: '강남 → 출입구', note: '이동 구간', minutes: 2, distanceMeters: 120 },
      { mode: 'walk', title: '출입구 → 광장', note: '이동 구간', minutes: 3 },
    ])
    render(<RouteTimeline route={value} />)
    expect(screen.getByText('강남 → 출입구')).toBeTruthy()
    expect(screen.getByText('출입구 → 광장')).toBeTruthy()
    expect(screen.getByText('도보 120m')).toBeTruthy()
  })

  it('backend endpoint pair를 서비스 카드에 중복하지 않고 노선 메모를 표시한다', () => {
    const value = route([
      {
        mode: 'subway',
        title: '역삼역 → 선릉역',
        note: '2호선',
        minutes: 4,
        routeId: '1002',
        from: { id: 'a', name: '역삼역' },
        to: { id: 'b', name: '선릉역' },
      },
    ])

    const { container } = render(<RouteTimeline route={value} />)
    const service = container.querySelector('.route-timeline-service')!
    expect(within(service as HTMLElement).getByText('2호선')).toBeTruthy()
    expect(within(service as HTMLElement).queryByText('역삼역 → 선릉역')).toBeNull()
    expect(container.querySelectorAll('.route-timeline-stop strong')).toHaveLength(2)
  })

  it('fixture 노선 방향과 중간 정차 정보를 모두 보존한다', () => {
    const value = route([
      {
        mode: 'subway',
        title: '수인분당선 수원 방면',
        note: '선릉역 → 한티역 → 도곡역',
        minutes: 6,
        routeId: '1075',
        from: { name: '선릉역' },
        to: { name: '도곡역' },
      },
    ])

    const { container } = render(<RouteTimeline route={value} />)
    const service = container.querySelector('.route-timeline-service')!
    expect(within(service as HTMLElement).getByText('수인분당선 수원 방면')).toBeTruthy()
    expect(within(service as HTMLElement).getByText('선릉역 → 한티역 → 도곡역')).toBeTruthy()
  })

  it('출발지와 첫 승차역이 같으면 텍스트를 반복하지 않고 출발 태그를 붙인다', () => {
    const value = route([
      {
        mode: 'subway',
        title: '역삼역 → 선릉역',
        note: '2호선',
        minutes: 4,
        from: { name: '역삼역' },
        to: { name: '선릉역' },
      },
    ])

    const { container } = render(<RouteTimeline route={value} originName="역삼역" />)
    expect(screen.getAllByText('역삼역')).toHaveLength(1)
    expect(container.querySelector('.route-timeline-end-tag')?.textContent).toBe('출발')
    expect(container.querySelector('.route-timeline-origin')).toBeNull()
  })

  it('명시적 전환과 같은 역에서 걷는 환승 구간의 원본 인덱스를 유지한다', () => {
    const value = route([
      {
        mode: 'walk',
        title: '정류장에서 승차',
        note: '승차',
        transitionType: 'BOARDING',
        minutes: 1,
        from: { name: '정류장' },
      },
      {
        mode: 'subway',
        title: '선릉역 → 강남역',
        note: '2호선 잠실 방면',
        minutes: 3,
        from: { name: '선릉역' },
        to: { name: '강남역' },
      },
      {
        mode: 'walk',
        title: '선릉역에서 환승',
        note: '수인분당선 승강장',
        transfer: true,
        minutes: 2,
        from: { id: 'station', name: '선릉역' },
        to: { id: 'station', name: '선릉역' },
      },
      {
        mode: 'subway',
        title: '선릉역 → 한티역',
        note: '수인분당선 수원 방면',
        minutes: 2,
        from: { name: '선릉역' },
        to: { name: '한티역' },
      },
    ])

    const { container } = render(<RouteTimeline route={value} activeIndex={3} />)
    const items = [...container.querySelectorAll<HTMLElement>('.route-timeline-leg')]
    expect(items.map((item) => item.dataset.legIndex)).toEqual(['0', '1', '2', '3'])
    expect(items[0].textContent).toContain('정류장에서 승차')
    expect(items[0].textContent).toContain('승차')
    expect(items[2].textContent).toContain('선릉역에서 환승')
    expect(items[2].textContent).toContain('환승')
    expect(items[3].getAttribute('aria-current')).toBe('step')
    expect(items[2].getAttribute('aria-current')).toBeNull()
  })

  it('혼잡도 접근성 라벨과 버스 대안·간격을 표시하고 endpoint가 없으면 경로명으로 보완한다', () => {
    const value = route([
      {
        mode: 'bus',
        title: '강남역 → 도곡역',
        note: '108번 · 143번',
        minutes: 8,
        segmentCongestionGrade: 'CONGESTED',
        busRouteOptions: [
          { routeId: '108', routeName: '108번', headwayMin: 10 },
          { routeId: '143', routeName: '143번', headwayMin: 12 },
        ],
      },
    ])

    const { container } = render(<RouteTimeline route={value} />)
    expect(screen.getByLabelText('구간 예상 혼잡도 혼잡')).toBeTruthy()
    expect(screen.getByText('이용 가능한 버스 2개 노선')).toBeTruthy()
    const options = container.querySelector('.route-timeline-bus-options')!
    expect(options.textContent).toContain('108번')
    expect(options.textContent).toContain('약 10분 간격')
    expect(options.textContent).toContain('143번')
    expect(options.textContent).toContain('약 12분 간격')
    expect(screen.getByText('강남역')).toBeTruthy()
    expect(screen.getByText('도곡역')).toBeTruthy()
  })
})
