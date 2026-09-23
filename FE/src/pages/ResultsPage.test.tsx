// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { places, routes } from '../api/mock/fixtures'
import type { ComponentProps } from 'react'
import type { Mode } from '../features/route/types'
import ResultsPage from './ResultsPage'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

function props(overrides: Partial<ComponentProps<typeof ResultsPage>> = {}) {
  return {
    origin: places[0],
    destinationName: places[1].name,
    visible: [],
    selectedId: null,
    setSelectedId: vi.fn(),
    status: 'success' as const,
    retry: vi.fn(),
    error: '',
    enabled: ['walk', 'subway', 'bus', 'bike'] as Mode[],
    priority: 'fast' as const,
    setPriority: vi.fn(),
    openFilter: vi.fn(),
    openSearch: vi.fn(),
    onBackToInput: vi.fn(),
    go: vi.fn(),
    startGuide: vi.fn(),
    canSwap: true,
    swapPlaces: vi.fn(),
    onResetModes: vi.fn(),
    onSearchWalk: vi.fn(),
    ...overrides,
  }
}

describe('경로 결과 상태', () => {
  it('구간 막대에서 환승을 도보와 다른 아이콘과 문구로 표시한다', () => {
    const route = {
      ...routes[0],
      legs: [
        { mode: 'walk' as const, title: '도보', note: '도보', minutes: 1 },
        { mode: 'walk' as const, title: '환승', note: '환승', minutes: 3, transfer: true },
        { mode: 'bike' as const, title: '자전거', note: '자전거', minutes: 6 },
        { mode: 'walk' as const, title: '환승', note: '환승', minutes: 3, transfer: true },
        { mode: 'walk' as const, title: '도보', note: '도보', minutes: 1 },
      ],
    }
    render(<ResultsPage {...props({ visible: [route] })} />)
    const strip = screen.getByLabelText('구간별 이동 시간')
    expect(strip.querySelectorAll('.transfer')).toHaveLength(2)
    expect(strip.querySelectorAll('.transfer .lucide-arrow-left-right')).toHaveLength(2)
    expect(strip.querySelectorAll('.walk .lucide-footprints')).toHaveLength(2)
    expect(screen.getAllByTitle('환승 3분')).toHaveLength(2)
  })
  it('경로의 구간을 눌러도 해당 경로를 선택하고 상세로 이동한다', () => {
    const setSelectedId = vi.fn()
    const go = vi.fn()
    const route = {
      ...routes[0],
      id: 'station-route',
      line: '2호선 · 수인분당선',
      legs: [
        {
          mode: 'subway' as const,
          title: '역삼 → 선릉',
          note: '2호선',
          minutes: 3,
          from: { name: '역삼' },
          to: { name: '선릉' },
        },
      ],
    }
    render(<ResultsPage {...props({ visible: [route], setSelectedId, go })} />)
    expect(screen.queryByText('2호선 · 수인분당선')).toBeNull()
    expect(screen.queryByText('상세 이동 경로')).toBeNull()
    expect(screen.queryByText('역삼 → 선릉')).toBeNull()
    expect(screen.getByRole('heading', { name: /추천 경로/ })).toBeTruthy()
    fireEvent.click(screen.getByText('역삼'))
    expect(setSelectedId).toHaveBeenCalledWith('station-route')
    expect(go).toHaveBeenCalledWith('detail')
  })
  it('검색 결과 경로 요약에서는 도보 행을 숨기고 이동수단 행만 표시한다', () => {
    const route = {
      ...routes[0],
      legs: [
        { mode: 'walk' as const, title: '출발지 → 역', note: '도보', minutes: 2 },
        { mode: 'subway' as const, title: '역 → 환승역', note: '2호선', minutes: 5 },
        { mode: 'walk' as const, title: '환승 이동', note: '도보', minutes: 1 },
        { mode: 'bus' as const, title: '정류장 → 도착', note: '420', minutes: 7 },
        { mode: 'walk' as const, title: '도착 이동', note: '도보', minutes: 2 },
      ],
    }
    render(<ResultsPage {...props({ visible: [route] })} />)

    const stops = screen.getByText('역').closest('.route-stops')
    expect(stops?.querySelectorAll('.walk')).toHaveLength(0)
    expect(stops?.querySelectorAll('.route-stop > .leg-icon.subway')).toHaveLength(1)
    expect(stops?.querySelectorAll('.route-stop > .leg-icon.bus')).toHaveLength(1)
  })
  it('조회 실패는 빈 검색 결과와 구분해 표시하고 재시도할 수 있다', () => {
    const retry = vi.fn()
    render(<ResultsPage {...props({ status: 'error', error: '', retry })} />)

    expect(screen.getByRole('alert').textContent).toContain('경로를 불러오지 못했어요.')
    expect(screen.queryByText('해당 수단으로는 경로가 없어요')).toBeNull()
    expect(screen.queryByText('추천 경로')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('검색 예외 코드는 원인에 맞는 복구 액션으로 연결된다', () => {
    const onBackToInput = vi.fn()
    const openFilter = vi.fn()
    const { rerender } = render(
      <ResultsPage
        {...props({
          status: 'error',
          errorCode: 'access-candidate-not-found',
          onBackToInput,
          openFilter,
        })}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '출발·도착지 수정' }))
    fireEvent.click(screen.getByRole('button', { name: '이동수단 변경' }))
    expect(onBackToInput).toHaveBeenCalledOnce()
    expect(openFilter).toHaveBeenCalledOnce()

    rerender(
      <ResultsPage
        {...props({
          status: 'error',
          errorCode: 'service-ended',
          openFilter,
        })}
      />,
    )
    expect(screen.getByRole('button', { name: '출발 시간 변경' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '이동수단 변경' })).toBeTruthy()
  })

  it('빈 결과에서 전체 수단과 도보 재검색을 제공한다', () => {
    const onResetModes = vi.fn()
    const onSearchWalk = vi.fn()
    render(<ResultsPage {...props({ onResetModes, onSearchWalk })} />)
    fireEvent.click(screen.getByRole('button', { name: '전체 수단으로 다시 검색' }))
    fireEvent.click(screen.getByRole('button', { name: '도보만 다시 검색' }))
    expect(onResetModes).toHaveBeenCalledOnce()
    expect(onSearchWalk).toHaveBeenCalledOnce()
  })

  it('성공했지만 결과가 없으면 조건 변경으로 필터를 연다', () => {
    const openFilter = vi.fn()
    const retry = vi.fn()
    render(<ResultsPage {...props({ openFilter, retry })} />)

    expect(screen.getByText('해당 수단으로는 경로가 없어요')).toBeTruthy()
    expect(screen.queryByText('경로를 불러오지 못했어요.')).toBeNull()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '조건 변경' }))
    expect(openFilter).toHaveBeenCalledOnce()
    expect(retry).not.toHaveBeenCalled()
  })

  it('출발지와 도착지 요약 칸을 각각 수정 검색으로 연다', () => {
    const openSearch = vi.fn()
    render(<ResultsPage {...props({ openSearch })} />)

    fireEvent.click(screen.getByRole('button', { name: '출발지 수정' }))
    fireEvent.click(screen.getByRole('button', { name: '도착지 수정' }))

    expect(openSearch.mock.calls).toEqual([['origin'], ['destination']])
  })

  it('경로 입력으로 돌아가기를 요청한다', () => {
    const onBackToInput = vi.fn()
    render(<ResultsPage {...props({ onBackToInput })} />)

    fireEvent.click(screen.getByRole('button', { name: '경로 입력으로 돌아가기' }))

    expect(onBackToInput).toHaveBeenCalledOnce()
  })

  it('경로 카드에 혼잡도 등급 글자만 표시하고 근거 문구는 숨긴다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    render(<ResultsPage {...props({ visible: routes.slice(0, 2) })} />)

    expect(screen.getAllByText('혼잡도 예상')).toHaveLength(2)
    const predictions = document.querySelectorAll('.route-card-prediction')
    expect(predictions).toHaveLength(2)
    expect(predictions[0].textContent).not.toContain('%')
    expect(predictions[0].textContent).toContain('보통')
    expect(predictions[1].textContent).not.toContain('%')
    expect(predictions[1].textContent).toContain('여유')
    expect(screen.queryByText('최근 7일 데이터 기반')).toBeNull()
    expect(screen.queryByText(/혼잡 \d+구간/)).toBeNull()
  })

  it('추천 경로를 먼저 보여주고 다른 경로만 로컬 정렬한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    const calmFeatured = {
      ...routes[1],
      congestionPrediction: { ...routes[1].congestionPrediction!, congestionPercent: 5 },
    }
    const remainingFast = {
      ...routes[2],
      id: 'remaining-fast',
      minutes: 16,
      congestionPrediction: { ...routes[2].congestionPrediction!, congestionPercent: 80 },
    }
    const remainingCalm = {
      ...routes[3],
      id: 'remaining-calm',
      minutes: 21,
      congestionPrediction: { ...routes[3].congestionPrediction!, congestionPercent: 20 },
    }
    render(
      <ResultsPage
        {...props({ visible: [routes[0], calmFeatured, remainingFast, remainingCalm] })}
      />,
    )

    const recommended = screen.getByRole('region', { name: '추천 경로' })
    const other = screen.getByRole('region', { name: '다른 경로' })
    expect(recommended.textContent).toContain('가장 빠른 경로')
    expect(recommended.textContent).toContain('덜 붐비는 경로')
    expect(other.textContent).toContain('빠른 순')
    expect(other.textContent).toContain('덜 붐비는 순')

    const otherCards = () => Array.from(other.querySelectorAll<HTMLButtonElement>('.route-card'))
    expect(otherCards()[0].getAttribute('aria-label')).toContain('지하철 경로')
    fireEvent.click(screen.getByRole('button', { name: '덜 붐비는 순' }))
    expect(otherCards()[0].getAttribute('aria-label')).toContain('버스 경로')
  })

  it('추천 경로가 같은 경로면 두 배지를 한 카드에 표시한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    const both = {
      ...routes[0],
      id: 'both',
      minutes: 15,
      routeType: 'LOW_CONGESTION' as const,
    }
    render(<ResultsPage {...props({ visible: [both, routes[1]] })} />)

    const card = screen.getByRole('button', { name: /가장 빠른 경로.*덜 붐비는 경로/ })
    expect(card.querySelectorAll('.route-recommendation-badge')).toHaveLength(2)
  })

  it('서버 혼잡도 표식만 있을 때도 추천하고 남은 경로의 혼잡도 정렬은 막는다', () => {
    const withoutPrediction = ({ congestionPrediction: _, ...route }: (typeof routes)[number]) =>
      route
    const liveRoutes = routes.map(withoutPrediction).map((route, index) => ({
      ...route,
      id: `live-${index}`,
      routeType: index === 1 ? ('LOW_CONGESTION' as const) : ('ALTERNATIVE' as const),
    }))
    render(<ResultsPage {...props({ visible: liveRoutes, isLiveApi: true })} />)

    expect(screen.getByRole('region', { name: '추천 경로' }).textContent).toContain(
      '덜 붐비는 경로',
    )
    expect(
      (screen.getByRole('button', { name: '덜 붐비는 순' }) as HTMLButtonElement).disabled,
    ).toBe(true)
  })

  it('출발·도착 교환을 요청한다', () => {
    const swapPlaces = vi.fn()
    render(<ResultsPage {...props({ swapPlaces })} />)

    fireEvent.click(screen.getByRole('button', { name: '출발지와 도착지 교환' }))

    expect(swapPlaces).toHaveBeenCalledOnce()
  })

  it('도착지가 없으면 출발·도착 교환을 막는다', () => {
    const swapPlaces = vi.fn()
    render(<ResultsPage {...props({ canSwap: false, swapPlaces })} />)

    expect(
      (screen.getByRole('button', { name: '출발지와 도착지 교환' }) as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(swapPlaces).not.toHaveBeenCalled()
  })
})
