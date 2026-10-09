// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RECENT_PLACES_STORAGE_KEY } from '../features/route/recentPlaces'
import type { Place } from '../features/route/types'
import type { FavoritePlace } from '../features/route/favoritePlaces'
import SearchPage from './SearchPage'

const favoriteProps = {
  favorites: [] as FavoritePlace[],
  isFavorite: () => false,
  toggleFavorite: vi.fn(),
}
const sample: Place = {
  id: 'station-1',
  name: '역삼역',
  address: '서울 강남구 테헤란로 지하 156',
  kind: '역',
  lat: 37.5006,
  lng: 127.0365,
}

const originalGeolocation = Object.getOwnPropertyDescriptor(navigator, 'geolocation')

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  localStorage.clear()
  if (originalGeolocation) Object.defineProperty(navigator, 'geolocation', originalGeolocation)
  else Reflect.deleteProperty(navigator, 'geolocation')
})

describe('장소 검색 화면', () => {
  it('현재 위치를 출발지로 적용하지만 최근 검색에는 저장하지 않는다', () => {
    const getCurrentPosition = vi.fn()
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition },
    })
    const choosePlace = vi.fn(() => true)
    render(
      <SearchPage
        searchTarget="origin"
        cancelSearch={vi.fn()}
        choosePlace={choosePlace}
        {...favoriteProps}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '현재 위치에서 출발' }))
    act(() =>
      getCurrentPosition.mock.calls[0][0]({
        coords: { latitude: 37.5, longitude: 127.03 },
      }),
    )

    expect(choosePlace).toHaveBeenCalledWith(
      expect.objectContaining({ name: '현재 위치', lat: 37.5, lng: 127.03 }),
    )
    expect(localStorage.getItem(RECENT_PLACES_STORAGE_KEY)).toBeNull()
  })

  it('확인 키로 검색 입력의 포커스를 닫되 한글 조합 중에는 유지한다', () => {
    render(
      <SearchPage
        searchTarget="origin"
        cancelSearch={vi.fn()}
        choosePlace={vi.fn()}
        {...favoriteProps}
      />,
    )
    const input = screen.getByRole('textbox', { name: '장소 검색어' })

    input.focus()
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
    expect(document.activeElement).not.toBe(input)

    input.focus()
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', isComposing: true })
    expect(document.activeElement).toBe(input)
  })

  it('즐겨찾기 섹션을 최근 검색 위에 보여 주고 집·회사 배지를 표시한다', () => {
    localStorage.setItem(RECENT_PLACES_STORAGE_KEY, JSON.stringify([{ ...sample, id: 'recent-1' }]))
    const favorites: FavoritePlace[] = [
      { place: sample, label: 'home', savedAt: '2026-10-01T00:00:00.000Z' },
    ]
    render(
      <SearchPage
        searchTarget="destination"
        cancelSearch={vi.fn()}
        choosePlace={vi.fn()}
        {...favoriteProps}
        favorites={favorites}
      />,
    )
    const labels = screen.getAllByText(/^(즐겨찾기|최근 검색)$/, { selector: 'p' })
    expect(labels.map((node) => node.textContent)).toEqual(['즐겨찾기', '최근 검색'])
    expect(screen.getByText('집', { selector: 'small' })).toBeTruthy()
  })

  it('별 토글은 즐겨찾기만 바꾸고 장소를 선택하지 않는다', () => {
    localStorage.setItem(RECENT_PLACES_STORAGE_KEY, JSON.stringify([sample]))
    const choosePlace = vi.fn()
    const toggleFavorite = vi.fn()
    render(
      <SearchPage
        searchTarget="destination"
        cancelSearch={vi.fn()}
        choosePlace={choosePlace}
        {...favoriteProps}
        toggleFavorite={toggleFavorite}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '역삼역 즐겨찾기 추가' }))
    expect(toggleFavorite).toHaveBeenCalledWith(sample)
    expect(choosePlace).not.toHaveBeenCalled()
  })

  it('집 등록 대상이면 제목을 바꾸고 현재 위치 버튼을 숨긴다', () => {
    render(
      <SearchPage
        searchTarget="home"
        cancelSearch={vi.fn()}
        choosePlace={vi.fn()}
        {...favoriteProps}
      />,
    )
    expect(screen.getByRole('heading', { name: '집 등록' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '현재 위치에서 출발' })).toBeNull()
  })
})
