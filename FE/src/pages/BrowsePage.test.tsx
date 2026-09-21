// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Place } from '../features/route/types'
import BrowsePage from './BrowsePage'

const mocks = vi.hoisted(() => ({
  usePlaceSearch: vi.fn(),
}))
vi.mock('../features/route/usePlaceSearch', () => ({ usePlaceSearch: mocks.usePlaceSearch }))
vi.mock('../features/map/KakaoMap', () => ({
  default: ({
    focusedPlace,
    onPlaceSelect,
  }: {
    focusedPlace: Place | null
    onPlaceSelect: (place: Place) => void
  }) => (
    <button type="button" aria-label="지도에서 장소 선택" onClick={() => onPlaceSelect(places[1])}>
      {focusedPlace?.name || '지도'}
    </button>
  ),
}))

const places: Place[] = [
  {
    id: 'station-1',
    name: '역삼역',
    address: '서울 강남구 테헤란로 지하 156',
    kind: '역',
    lat: 37.5006,
    lng: 127.0365,
  },
  {
    id: 'station-2',
    name: '선릉역',
    address: '서울 강남구 선릉로 지하 525',
    kind: '역',
    lat: 37.5045,
    lng: 127.0489,
  },
]

beforeEach(() => {
  mocks.usePlaceSearch.mockImplementation((query: string) => ({
    places: query.trim() ? places : [],
    loading: false,
    error: '',
  }))
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('일반 장소 탐색 화면', () => {
  it('빈 화면은 접혀 있고 첫 검색 결과에서 기본 높이로 열린다', () => {
    const { container } = render(
      <BrowsePage onBack={vi.fn()} onMessage={vi.fn()} setOrigin={vi.fn()} findRoutes={vi.fn()} />,
    )
    const sheet = () => container.querySelector('.bottom-sheet')
    expect(sheet()?.getAttribute('data-snap')).toBe('collapsed')

    fireEvent.change(screen.getByRole('textbox', { name: '탐색할 장소 검색어' }), {
      target: { value: '역' },
    })
    expect(sheet()?.getAttribute('data-snap')).toBe('default')
  })

  it('검색 결과에서 사용자가 펼친 시트는 결과 갱신 때 유지하고 검색어를 비우면 접는다', () => {
    const { container } = render(
      <BrowsePage onBack={vi.fn()} onMessage={vi.fn()} setOrigin={vi.fn()} findRoutes={vi.fn()} />,
    )
    const input = screen.getByRole('textbox', { name: '탐색할 장소 검색어' })
    fireEvent.change(input, { target: { value: '역' } })
    const sheet = () => container.querySelector('.bottom-sheet')
    fireEvent.keyDown(screen.getByRole('button', { name: '바텀시트 펼치기' }), {
      key: 'ArrowUp',
    })
    expect(sheet()?.getAttribute('data-snap')).toBe('expanded')

    fireEvent.change(input, { target: { value: '선릉' } })
    expect(sheet()?.getAttribute('data-snap')).toBe('expanded')
    fireEvent.click(screen.getByRole('button', { name: '검색어 지우기' }))
    expect(sheet()?.getAttribute('data-snap')).toBe('collapsed')
  })

  it('장소 선택만으로 경로를 요청하지 않고 명시한 설정 버튼에서만 연결한다', () => {
    const setOrigin = vi.fn(() => true)
    const findRoutes = vi.fn(() => true)
    render(
      <BrowsePage
        onBack={vi.fn()}
        onMessage={vi.fn()}
        setOrigin={setOrigin}
        findRoutes={findRoutes}
      />,
    )

    fireEvent.change(screen.getByRole('textbox', { name: '탐색할 장소 검색어' }), {
      target: { value: '역' },
    })
    fireEvent.click(screen.getByRole('button', { name: /역삼역/ }))
    expect(screen.getByRole('region', { name: '선택한 장소' }).textContent).toContain('역삼역')
    expect(setOrigin).not.toHaveBeenCalled()
    expect(findRoutes).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '출발지로 설정' }))
    expect(setOrigin).toHaveBeenCalledWith(places[0])
    expect(findRoutes).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '지도에서 장소 선택' }))
    expect(screen.getByRole('region', { name: '선택한 장소' }).textContent).toContain('선릉역')
    fireEvent.click(screen.getByRole('button', { name: '도착지로 설정' }))
    expect(findRoutes).toHaveBeenCalledWith(places[1])
  })

  it('장소를 선택하면 시트를 접고 선택 카드를 닫으면 결과 높이로 돌아간다', () => {
    const { container } = render(
      <BrowsePage onBack={vi.fn()} onMessage={vi.fn()} setOrigin={vi.fn()} findRoutes={vi.fn()} />,
    )
    const input = screen.getByRole('textbox', { name: '탐색할 장소 검색어' })
    fireEvent.change(input, { target: { value: '역' } })
    const sheet = () => container.querySelector('.bottom-sheet')
    fireEvent.click(screen.getByRole('button', { name: /역삼역/ }))
    expect(sheet()?.getAttribute('data-snap')).toBe('collapsed')
    expect(container.querySelector('.browse-place-list')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '장소 정보 닫기' }))
    expect(sheet()?.getAttribute('data-snap')).toBe('default')
    expect(container.querySelector('.browse-place-list')).not.toBeNull()
  })

  it('검색어가 바뀌면 선택 카드와 지도 focus를 지운다', () => {
    render(
      <BrowsePage onBack={vi.fn()} onMessage={vi.fn()} setOrigin={vi.fn()} findRoutes={vi.fn()} />,
    )
    const input = screen.getByRole('textbox', { name: '탐색할 장소 검색어' })
    fireEvent.change(input, { target: { value: '역' } })
    fireEvent.click(screen.getByRole('button', { name: /역삼역/ }))
    expect(screen.getByRole('region', { name: '선택한 장소' })).toBeTruthy()

    fireEvent.change(input, { target: { value: '선릉' } })
    expect(screen.queryByRole('region', { name: '선택한 장소' })).toBeNull()
    expect(screen.getByRole('button', { name: '지도에서 장소 선택' }).textContent).toBe('지도')
  })

  it('확인 키로 탐색 입력의 포커스를 닫되 한글 조합 중에는 유지한다', () => {
    render(
      <BrowsePage onBack={vi.fn()} onMessage={vi.fn()} setOrigin={vi.fn()} findRoutes={vi.fn()} />,
    )
    const input = screen.getByRole('textbox', { name: '탐색할 장소 검색어' })

    input.focus()
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
    expect(document.activeElement).not.toBe(input)

    input.focus()
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', isComposing: true })
    expect(document.activeElement).toBe(input)
  })
})
