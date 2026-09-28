// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RECENT_PLACES_STORAGE_KEY } from '../features/route/usePlaceSearch'
import SearchPage from './SearchPage'

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
    render(<SearchPage searchTarget="origin" cancelSearch={vi.fn()} choosePlace={choosePlace} />)

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
    render(<SearchPage searchTarget="origin" cancelSearch={vi.fn()} choosePlace={vi.fn()} />)
    const input = screen.getByRole('textbox', { name: '장소 검색어' })

    input.focus()
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
    expect(document.activeElement).not.toBe(input)

    input.focus()
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', isComposing: true })
    expect(document.activeElement).toBe(input)
  })
})
