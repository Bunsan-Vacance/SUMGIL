// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import HomePage from './HomePage'

const origin = {
  id: 'origin',
  name: '강남역',
  address: '서울 강남구 강남대로',
  kind: '지하철역',
}

afterEach(cleanup)

describe('홈 길찾기 패널', () => {
  it('초기 출발지는 임의의 장소 대신 선택 안내를 표시한다', () => {
    render(
      <HomePage
        origin={{ id: 'empty-origin', name: '', address: '', kind: '장소' }}
        destination={null}
        openSearch={vi.fn()}
        routePanelOpen
        toggleRoutePanel={vi.fn()}
        findRoutes={vi.fn()}
        swapPlaces={vi.fn()}
      />,
    )

    expect(screen.getByText('출발지를 검색하세요')).toBeTruthy()
  })

  it('단독 장소 검색 없이 길찾기 패널을 열고 닫는다', () => {
    const toggleRoutePanel = vi.fn()
    const { rerender } = render(
      <HomePage
        origin={origin}
        destination={null}
        openSearch={vi.fn()}
        routePanelOpen={false}
        toggleRoutePanel={toggleRoutePanel}
        findRoutes={vi.fn()}
        swapPlaces={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button', { name: '장소, 역, 주소 검색' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /길찾기/ }))
    expect(toggleRoutePanel).toHaveBeenCalledOnce()
    expect(document.getElementById('home-route-panel')?.getAttribute('hidden')).toBe('')

    rerender(
      <HomePage
        origin={origin}
        destination={null}
        openSearch={vi.fn()}
        routePanelOpen
        toggleRoutePanel={toggleRoutePanel}
        findRoutes={vi.fn()}
        swapPlaces={vi.fn()}
      />,
    )
    expect(screen.queryByRole('button', { name: '홈으로 돌아가기' })).toBeNull()
  })

  it('패널 안의 출발지·도착지 입력은 기존 검색 흐름을 호출한다', () => {
    const openSearch = vi.fn()
    render(
      <HomePage
        origin={origin}
        destination={null}
        openSearch={openSearch}
        routePanelOpen
        toggleRoutePanel={vi.fn()}
        findRoutes={vi.fn()}
        swapPlaces={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /출발.*강남역/ }))
    fireEvent.click(screen.getByRole('button', { name: /도착.*도착지를 검색하세요/ }))
    expect(openSearch).toHaveBeenNthCalledWith(1, 'origin')
    expect(openSearch).toHaveBeenNthCalledWith(2, 'destination')
  })

  it('도착지가 없으면 같은 입력 상자의 교환 버튼을 비활성화한다', () => {
    const swapPlaces = vi.fn()
    render(
      <HomePage
        origin={origin}
        destination={null}
        openSearch={vi.fn()}
        routePanelOpen
        toggleRoutePanel={vi.fn()}
        findRoutes={vi.fn()}
        swapPlaces={swapPlaces}
      />,
    )

    const swap = screen.getByRole('button', { name: '출발지와 도착지 교환' })
    expect(swap.getAttribute('disabled')).toBe('')
    fireEvent.click(swap)
    expect(swapPlaces).not.toHaveBeenCalled()
  })
})
