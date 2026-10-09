// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CongestionBatch, CongestionBatchRepository } from '../../api/congestion'
import type { TrainArrivalResult } from '../../api/guidance'
import StationCard from './StationCard'
import type { StationCongestion } from './useNearbyStationCongestion'
import { hourlyDepartureTimes } from './useStationHourlyCongestion'

// 서울 2026-10-09 18:37
const NOW = new Date('2026-10-09T09:37:00.000Z')
const now = () => NOW

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const station: StationCongestion = {
  stationId: '222',
  stationName: '강남',
  lat: 37.4979,
  lng: 127.0276,
  distanceMeters: 161,
  lines: [
    { lineId: '1002', lineName: '2호선' },
    { lineId: '1077', lineName: '신분당선' },
  ],
  level: 85,
  grade: 'CONGESTED',
  updatedAt: null,
}

const train = (id: string, direction: string, minutes: number) => ({
  trainId: id,
  direction,
  arrivalTime: new Date(NOW.getTime() + minutes * 60000).toISOString(),
  updatedAt: NOW.toISOString(),
  source: 'LIVE' as const,
})
const live = (): TrainArrivalResult => ({
  status: 'LIVE',
  updatedAt: '2026-10-09T09:36:30.000Z',
  trains: [train('a', '내선', 3), train('b', '내선', 9), train('c', '외선', 5)],
})
const times = hourlyDepartureTimes(NOW)
const batchOf = (levels: Array<number | null>): CongestionBatch => ({
  targetType: 'STATION',
  departureTimes: times,
  targets: [
    {
      targetId: '222',
      slots: levels.map((level, index) => ({
        departureTime: times[index],
        dowType: 0,
        timeSlot: 0,
        level,
        source: null,
        updatedAt: null,
      })),
    },
  ],
})

function setup(
  options: {
    arrivals?: ReturnType<typeof vi.fn>
    batch?: ReturnType<typeof vi.fn>
    station?: StationCongestion
    props?: Partial<React.ComponentProps<typeof StationCard>>
  } = {},
) {
  const arrivals = options.arrivals ?? vi.fn(async () => live())
  const batch = options.batch ?? vi.fn(async () => batchOf([20, 85, null, 45, 110, 30]))
  const handlers = {
    onToggleFavorite: vi.fn(),
    onClose: vi.fn(),
    onSetOrigin: vi.fn(),
    onSetDestination: vi.fn(),
  }
  const rendered = render(
    <StationCard
      station={options.station ?? station}
      favorite={false}
      {...handlers}
      arrivalsRepository={{ arrivals } as never}
      batchRepository={{ batch } as unknown as CongestionBatchRepository}
      now={now}
      {...options.props}
    />,
  )
  return { ...rendered, arrivals, batch, ...handlers }
}

const settle = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)))

describe('역 카드', () => {
  it('헤더에 역 이름·거리·환승역 노선 요약을 보여 준다', async () => {
    setup()
    await settle()
    expect(screen.getByRole('heading', { level: 2, name: '강남역' })).toBeTruthy()
    expect(screen.getByText(/161m · 도보\s+3분/)).toBeTruthy()
    expect(screen.getByText('2호선 · 신분당선 환승역')).toBeTruthy()
  })

  it('노선이 하나면 탭을 그리지 않고 노선이 없으면 지하철역과 안내를 보여 준다', async () => {
    const single = setup({ station: { ...station, lines: [station.lines[0]] } })
    await settle()
    expect(screen.queryByRole('group', { name: '노선 선택' })).toBeNull()
    single.unmount()

    const none = setup({ station: { ...station, lines: [] } })
    await settle()
    expect(screen.getByText('지하철역')).toBeTruthy()
    expect(screen.getByText('노선 정보가 없어 도착 정보를 볼 수 없어요')).toBeTruthy()
    expect(none.arrivals).not.toHaveBeenCalled()
  })

  it('노선 탭을 바꾸면 새 노선으로 도착 정보를 다시 조회한다', async () => {
    const { arrivals } = setup()
    await settle()
    const group = screen.getByRole('group', { name: '노선 선택' })
    expect(within(group).getAllByRole('button')).toHaveLength(2)
    expect(arrivals.mock.calls[0][0]).toMatchObject({ routeId: '1002', routeName: '2호선' })
    fireEvent.click(within(group).getByRole('button', { name: /신분당선/ }))
    await settle()
    expect(arrivals.mock.calls.at(-1)?.[0]).toMatchObject({
      routeId: '1077',
      routeName: '신분당선',
    })
  })

  it('실시간 도착은 방면별 도착 시간과 기준 시각을 보여 준다', async () => {
    setup()
    await settle()
    expect(screen.getByText('내선')).toBeTruthy()
    expect(screen.getByText('3분 후')).toBeTruthy()
    expect(screen.getByText('9분 후')).toBeTruthy()
    expect(screen.getByText('5분 후')).toBeTruthy()
    expect(screen.getByText('18:36:30 기준')).toBeTruthy()
  })

  it('STALE이면 마지막 갱신 시각을 함께 보여 준다', async () => {
    setup({ arrivals: vi.fn(async () => ({ ...live(), status: 'STALE' as const })) })
    await settle()
    expect(screen.getByText('마지막 갱신 18:36')).toBeTruthy()
    expect(screen.getByText('3분 후')).toBeTruthy()
  })

  it('NO_INFO·OUTSIDE_WINDOW·열차 없음 문구를 구분한다', async () => {
    const noInfo = setup({
      arrivals: vi.fn(async () => ({ status: 'NO_INFO' as const, trains: [], updatedAt: null })),
    })
    await settle()
    expect(screen.getByText('도착 정보가 없어요')).toBeTruthy()
    noInfo.unmount()
    const outside = setup({
      arrivals: vi.fn(async () => ({
        status: 'OUTSIDE_WINDOW' as const,
        trains: [],
        updatedAt: null,
      })),
    })
    await settle()
    expect(screen.getByText('운행 시간이 아니에요')).toBeTruthy()
    outside.unmount()
    setup({
      arrivals: vi.fn(async () => ({ status: 'STALE' as const, trains: [], updatedAt: null })),
    })
    await settle()
    expect(screen.getByText('도착 예정 열차가 없어요')).toBeTruthy()
  })

  it('도착 조회가 실패하면 안내와 다시 시도 버튼을 보여 준다', async () => {
    const arrivals = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue(live())
    setup({ arrivals })
    await settle()
    expect(screen.getByText('도착 정보를 불러오지 못했어요')).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: '다시 시도' })[0])
    await settle()
    expect(screen.getByText('3분 후')).toBeTruthy()
  })

  it('시간대별 막대 6개와 지금 강조·접근성 문구·요약을 보여 준다', async () => {
    const { container } = setup()
    await settle()
    const bars = container.querySelectorAll('.station-card-bar')
    expect(bars).toHaveLength(6)
    expect(bars[0].classList.contains('grade-relaxed')).toBe(true)
    expect(bars[1].classList.contains('grade-congested')).toBe(true)
    expect(bars[1].classList.contains('now')).toBe(true)
    expect(bars[2].classList.contains('grade-none')).toBe(true)
    expect(bars[4].classList.contains('grade-saturated')).toBe(true)
    expect(screen.getByRole('img').getAttribute('aria-label')).toBe(
      '강남역 시간대별 혼잡도: 17시 여유, 지금 혼잡, 19시 정보 없음, 20시 보통, 21시 포화, 22시 여유',
    )
    expect(screen.getByText('지금 혼잡')).toBeTruthy()
    expect(screen.getByText('20시 이후 보통 수준으로 내려가요')).toBeTruthy()
    expect(screen.getByText('지금')).toBeTruthy()
  })

  it('지금 등급이 없으면 지금 정보 없음을 보여 준다', async () => {
    setup({
      station: { ...station, level: null, grade: null },
      batch: vi.fn(async () => batchOf([null, null, null, null, null, null])),
    })
    await settle()
    expect(screen.getByText('지금 정보 없음')).toBeTruthy()
  })

  it('시간대별 혼잡도 조회 실패와 저장소 없음을 구분한다', async () => {
    const failing = setup({ batch: vi.fn().mockRejectedValue(new Error('boom')) })
    await settle()
    expect(screen.getByText('혼잡도를 불러오지 못했어요')).toBeTruthy()
    failing.unmount()
    setup({ props: { batchRepository: null } })
    await settle()
    expect(screen.getByText('시간대별 혼잡도를 볼 수 없어요')).toBeTruthy()
  })

  it('출발·도착·즐겨찾기·닫기 버튼이 각 콜백을 호출한다', async () => {
    const { onSetOrigin, onSetDestination, onToggleFavorite, onClose } = setup()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: '출발지로 설정' }))
    fireEvent.click(screen.getByRole('button', { name: '도착지로 설정' }))
    fireEvent.click(screen.getByRole('button', { name: '즐겨찾기 추가' }))
    fireEvent.click(screen.getByRole('button', { name: '역 정보 닫기' }))
    const expected = expect.objectContaining({
      id: 'station:222:default',
      kind: '지하철역',
      stationId: '222',
    })
    expect(onSetOrigin).toHaveBeenCalledWith(expected)
    expect(onSetDestination).toHaveBeenCalledWith(expected)
    expect(onToggleFavorite).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalledOnce()
  })
})
