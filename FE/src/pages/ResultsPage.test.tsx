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
    expect(screen.queryByRole('heading', { name: /추천 경로/ })).toBeNull()
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

  it('경로 카드에 혼잡도 예상 퍼센트·등급·근거를 표시한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    render(<ResultsPage {...props({ visible: routes.slice(0, 2) })} />)

    expect(screen.getByText(/혼잡도 예상 68% · 보통/)).toBeTruthy()
    expect(screen.getByText(/혼잡도 예상 42% · 여유/)).toBeTruthy()
    expect(screen.getAllByText('최근 7일 데이터 기반')).toHaveLength(2)
    expect(screen.queryByText(/혼잡 \d+구간/)).toBeNull()
  })

  it('혼잡도를 비교할 수 있으면 정렬 메뉴에서 덜 붐비는 순을 선택한다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    const setPriority = vi.fn()
    render(<ResultsPage {...props({ visible: routes.slice(0, 2), setPriority })} />)

    fireEvent.click(screen.getByRole('button', { name: '경로 정렬: 빠른 순' }))
    fireEvent.click(screen.getByRole('menuitemradio', { name: '덜 붐비는 순' }))

    expect(setPriority).toHaveBeenCalledWith('calm')
  })

  it('혼잡도 없는 결과는 예측 정보 없음을 표시하고 정렬을 숨긴다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    const liveRoutes = routes
      .slice(0, 1)
      .map(({ congestionPrediction: _congestionPrediction, ...route }) => route)
    render(<ResultsPage {...props({ visible: liveRoutes, isLiveApi: true })} />)

    expect(screen.getByText('예측 정보 없음')).toBeTruthy()
    expect(screen.getByRole('button', { name: /예측 정보 없음/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /경로 정렬:/ })).toBeNull()
  })

  it('정렬 메뉴는 화살표 클릭과 키보드 이동을 지원하고 Esc 또는 바깥 클릭으로 닫힌다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-17T00:00:00.000Z'))
    render(<ResultsPage {...props({ visible: routes.slice(0, 2) })} />)
    const trigger = screen.getByRole('button', { name: '경로 정렬: 빠른 순' })
    fireEvent.click(trigger.querySelector('svg')!)
    const fast = screen.getByRole('menuitemradio', { name: '빠른 순' })
    expect(document.activeElement).toBe(fast)
    fireEvent.keyDown(fast, { key: 'ArrowDown' })
    const calm = screen.getByRole('menuitemradio', { name: '덜 붐비는 순' })
    expect(document.activeElement).toBe(calm)
    fireEvent.keyDown(calm, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    fireEvent.click(trigger)
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('menu')).toBeNull()
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
