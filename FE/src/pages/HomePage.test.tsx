// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FavoritePlace } from '../features/route/favoritePlaces'
import { pinRecentRoute, saveRecentRoute } from '../features/route/recentRoutes'
import type { OutlookState } from '../features/map/useBikeStationOutlook'
import type { HomeSelection } from '../features/map/useHomeMapLayers'
import type { Place } from '../features/route/types'
import HomePage from './HomePage'

// 역 카드의 조회 훅은 StationCard.test.tsx에서 검증하므로 여기서는 연결만 확인한다.
vi.mock('../features/map/StationCard', () => ({
  default: ({
    station,
    onClose,
    onSetDestination,
  }: {
    station: { stationName: string }
    onClose: () => void
    onSetDestination: (place: { id: string }) => void
  }) => (
    <section aria-label="선택한 역">
      <span>{station.stationName}</span>
      <button onClick={onClose}>역 정보 닫기</button>
      <button onClick={() => onSetDestination({ id: 'station:222:default' })}>역 도착 설정</button>
    </section>
  ),
}))

const origin = {
  id: 'origin',
  name: '강남역',
  address: '서울 강남구 강남대로',
  kind: '지하철역',
}

const baseProps = {
  openSearch: vi.fn(),
  findRoutesFrom: vi.fn(),
  toggleRoutePanel: vi.fn(),
  findRoutes: vi.fn(),
  swapPlaces: vi.fn(),
  favorites: [] as FavoritePlace[],
  home: null,
  work: null,
  openFavoriteRegistration: vi.fn(),
  selection: null as HomeSelection | null,
  outlook: {
    stock: { status: 'unavailable' },
    predictions: { in15: { status: 'unavailable' }, in30: { status: 'unavailable' } },
    retry: vi.fn(),
  } as OutlookState,
  clearSelection: vi.fn(),
  isFavorite: () => false,
  toggleFavorite: vi.fn(),
  setOriginFromStation: vi.fn(),
}
const favoriteOf = (id: string, label: FavoritePlace['label'] = null): FavoritePlace => ({
  place: { id, name: `장소 ${id}`, address: '서울', kind: '장소', lat: 37.5, lng: 127 },
  label,
  savedAt: '2026-10-01T00:00:00.000Z',
})

beforeEach(() => localStorage.clear())
afterEach(cleanup)

describe('홈 길찾기 패널', () => {
  it('초기 출발지는 임의의 장소 대신 선택 안내를 표시한다', () => {
    render(
      <HomePage
        {...baseProps}
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
        {...baseProps}
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
        {...baseProps}
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
        {...baseProps}
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
        {...baseProps}
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

  it('미등록 집 칩은 등록 화면을 열고 길찾기는 호출하지 않는다', () => {
    const openFavoriteRegistration = vi.fn()
    const findRoutes = vi.fn()
    render(
      <HomePage
        {...baseProps}
        origin={origin}
        destination={null}
        routePanelOpen={false}
        findRoutes={findRoutes}
        openFavoriteRegistration={openFavoriteRegistration}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '집 등록' }))
    expect(openFavoriteRegistration).toHaveBeenCalledWith('home')
    expect(findRoutes).not.toHaveBeenCalled()
  })

  it('등록된 집 칩은 해당 장소로 길찾기를 시작한다', () => {
    const findRoutes = vi.fn()
    const home = favoriteOf('home-1', 'home')
    render(
      <HomePage
        {...baseProps}
        origin={origin}
        destination={null}
        routePanelOpen={false}
        findRoutes={findRoutes}
        home={home}
        favorites={[home]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '집으로 길찾기' }))
    expect(findRoutes).toHaveBeenCalledWith(home.place)
  })

  it('label 없는 즐겨찾기 칩은 최대 5개만 보여 준다', () => {
    const favorites = Array.from({ length: 6 }, (_, index) => favoriteOf(String(index)))
    render(
      <HomePage
        {...baseProps}
        origin={origin}
        destination={null}
        routePanelOpen={false}
        favorites={favorites}
      />,
    )
    const group = screen.getByRole('group', { name: '자주 가는 곳' })
    expect(group.querySelectorAll('button')).toHaveLength(2 + 5)
    expect(screen.queryByRole('button', { name: '장소 5 길찾기' })).toBeNull()
  })

  it('검색창을 누르면 도착지 검색을 연다', () => {
    const openSearch = vi.fn()
    render(
      <HomePage
        {...baseProps}
        origin={origin}
        destination={null}
        routePanelOpen={false}
        openSearch={openSearch}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '도착지 검색' }))
    expect(openSearch).toHaveBeenCalledWith('destination')
  })

  it('상단 바와 칩 행은 패널이 닫혔을 때만 보인다', () => {
    const { rerender } = render(
      <HomePage {...baseProps} origin={origin} destination={null} routePanelOpen={false} />,
    )
    const topbar = document.querySelector('.home-topbar')
    expect(topbar?.hasAttribute('hidden')).toBe(false)
    expect(screen.getByRole('group', { name: '자주 가는 곳' })).toBeTruthy()
    expect(document.querySelector('#home-route-panel')?.hasAttribute('hidden')).toBe(true)
    rerender(<HomePage {...baseProps} origin={origin} destination={null} routePanelOpen />)
    expect(topbar?.hasAttribute('hidden')).toBe(true)
    expect(document.querySelector('#home-route-panel')?.hasAttribute('hidden')).toBe(false)
    expect(document.querySelector('#home-route-panel .home-chips')).not.toBeNull()
  })

  describe('최근 경로 시트', () => {
    const stationA = { id: 'a', name: '강남역', address: '서울', kind: '역', lat: 37.5, lng: 127 }
    const stationB = {
      id: 'b',
      name: '서울역',
      address: '서울',
      kind: '역',
      lat: 37.55,
      lng: 126.97,
    }
    // 시트는 접힌 채 시작하므로 기본으로 펼친 뒤 전체 목록을 확인한다.
    const renderHome = (props = {}, expand = true) => {
      const rendered = render(
        <HomePage
          {...baseProps}
          origin={origin}
          destination={null}
          routePanelOpen={false}
          {...props}
        />,
      )
      if (expand) fireEvent.click(screen.getByRole('button', { name: '최근 경로 펼치기' }))
      return rendered
    }

    it('초기에는 접혀 첫 경로 1개만 보이고 제목 버튼으로 펼치고 접는다', () => {
      saveRecentRoute(stationA, stationB, new Date('2026-10-08T00:00:00.000Z'))
      saveRecentRoute(stationB, stationA, new Date('2026-10-09T00:00:00.000Z'))
      renderHome({}, false)
      const sheet = document.querySelector('.home-sheet')!
      expect(sheet.getAttribute('data-snap')).toBe('collapsed')
      expect(document.querySelectorAll('.home-recent-route')).toHaveLength(1)
      expect(screen.queryByRole('button', { name: /최근 경로 삭제/ })).toBeNull()

      fireEvent.click(screen.getByRole('button', { name: '최근 경로 펼치기' }))
      expect(sheet.getAttribute('data-snap')).toBe('default')
      expect(document.querySelectorAll('.home-recent-route')).toHaveLength(2)
      expect(screen.getAllByRole('button', { name: /최근 경로 삭제/ })).toHaveLength(2)

      fireEvent.click(screen.getByRole('button', { name: '최근 경로 접기' }))
      expect(sheet.getAttribute('data-snap')).toBe('collapsed')
    })

    it('카드를 선택하면 펼치고 선택이 풀리면 다시 접는다', () => {
      const station = {
        stationId: '222',
        stationName: '강남',
        lat: 37.4979,
        lng: 127.0276,
        distanceMeters: 100,
        lines: [],
        level: null,
        grade: null,
        updatedAt: null,
      }
      const { rerender } = renderHome({}, false)
      const sheet = document.querySelector('.home-sheet')!
      expect(sheet.getAttribute('data-snap')).toBe('collapsed')
      rerender(
        <HomePage
          {...baseProps}
          origin={origin}
          destination={null}
          routePanelOpen={false}
          selection={{ kind: 'subway', station }}
        />,
      )
      expect(sheet.getAttribute('data-snap')).toBe('default')
      rerender(
        <HomePage
          {...baseProps}
          origin={origin}
          destination={null}
          routePanelOpen={false}
          selection={null}
        />,
      )
      expect(sheet.getAttribute('data-snap')).toBe('collapsed')
    })

    it('저장된 경로를 현재 위치·집 이름 규칙으로 표시한다', () => {
      saveRecentRoute(stationA, stationB)
      saveRecentRoute({ ...stationA, id: 'current-location:1', kind: '현재 위치' }, stationA)
      const home = { ...favoriteOf('a', 'home'), place: stationA }
      renderHome({ home, favorites: [home] })
      expect(screen.getByRole('button', { name: '현재 위치 → 집 경로 찾기' })).toBeTruthy()
      expect(screen.getByRole('button', { name: '집 → 서울역 경로 찾기' })).toBeTruthy()
    })

    it('탭하면 출발지가 있으면 findRoutesFrom, 없으면 findRoutes를 호출한다', () => {
      saveRecentRoute(stationA, stationB)
      saveRecentRoute({ ...stationA, id: 'current-location:1', kind: '현재 위치' }, stationB)
      const findRoutes = vi.fn()
      const findRoutesFrom = vi.fn()
      renderHome({ findRoutes, findRoutesFrom })
      fireEvent.click(screen.getByRole('button', { name: '강남역 → 서울역 경로 찾기' }))
      expect(findRoutesFrom).toHaveBeenCalledWith(stationA, stationB)
      fireEvent.click(screen.getByRole('button', { name: '현재 위치 → 서울역 경로 찾기' }))
      expect(findRoutes).toHaveBeenCalledWith(stationB)
    })

    it('삭제하면 목록에서 사라지고 비면 안내 문구를 보여 준다', () => {
      saveRecentRoute(stationA, stationB)
      renderHome()
      fireEvent.click(screen.getByRole('button', { name: '강남역 → 서울역 최근 경로 삭제' }))
      expect(screen.queryByRole('button', { name: /경로 찾기/ })).toBeNull()
      expect(screen.getByText('아직 찾은 경로가 없어요')).toBeTruthy()
    })

    it('저장한 경로는 맨 위에 별 아이콘과 저장 라벨로 나온다', () => {
      saveRecentRoute(stationA, stationB, new Date('2026-10-08T00:00:00.000Z'))
      pinRecentRoute(stationB, stationA, new Date('2026-10-01T00:00:00.000Z'))
      renderHome()
      const items = document.querySelectorAll('.home-recent-route')
      expect(items[0].classList.contains('pinned')).toBe(true)
      expect(items[1].classList.contains('pinned')).toBe(false)
      expect(screen.getByRole('button', { name: '서울역 → 강남역 저장한 경로 찾기' })).toBeTruthy()
      expect(screen.getByRole('button', { name: '강남역 → 서울역 경로 찾기' })).toBeTruthy()
    })

    it('패널이 열려 있어도 시트를 렌더링한다', () => {
      render(<HomePage {...baseProps} origin={origin} destination={null} routePanelOpen />)
      expect(document.querySelector('.home-sheet')).not.toBeNull()
    })
  })

  describe('선택한 대여소 카드', () => {
    const bike: Place = {
      id: 'bike-station:ST-1',
      name: '강남역 1번출구',
      address: '서울',
      kind: '따릉이 대여소',
      lat: 37.5,
      lng: 127,
    }
    const renderHome = (props = {}) =>
      render(
        <HomePage
          {...baseProps}
          origin={origin}
          destination={null}
          routePanelOpen={false}
          selection={{ kind: 'bike', place: bike }}
          {...props}
        />,
      )

    it('선택하면 카드를 보이고 최근 경로는 숨긴다', () => {
      renderHome()
      expect(screen.getByRole('region', { name: '선택한 따릉이 대여소' })).toBeTruthy()
      expect(screen.queryByText('최근 경로')).toBeNull()
    })

    it('닫기를 누르면 clearSelection을 호출한다', () => {
      const clearSelection = vi.fn()
      renderHome({ clearSelection })
      fireEvent.click(screen.getByRole('button', { name: '대여소 정보 닫기' }))
      expect(clearSelection).toHaveBeenCalledOnce()
    })

    it('도착지로 설정하면 길찾기를 시작하고 카드를 닫는다', () => {
      const findRoutes = vi.fn(() => true)
      const clearSelection = vi.fn()
      renderHome({ findRoutes, clearSelection })
      fireEvent.click(screen.getByRole('button', { name: '도착지로 설정' }))
      expect(findRoutes).toHaveBeenCalledWith(bike)
      expect(clearSelection).toHaveBeenCalledOnce()
    })

    it('도착지 설정이 거부되면 카드를 유지한다', () => {
      const clearSelection = vi.fn()
      renderHome({ findRoutes: vi.fn(() => false), clearSelection })
      fireEvent.click(screen.getByRole('button', { name: '도착지로 설정' }))
      expect(clearSelection).not.toHaveBeenCalled()
    })

    it('출발지로 설정하면 setOriginFromStation 후 카드를 닫는다', () => {
      const setOriginFromStation = vi.fn()
      const clearSelection = vi.fn()
      renderHome({ setOriginFromStation, clearSelection })
      fireEvent.click(screen.getByRole('button', { name: '출발지로 설정' }))
      expect(setOriginFromStation).toHaveBeenCalledWith(bike)
      expect(clearSelection).toHaveBeenCalledOnce()
    })
  })

  describe('선택한 역 카드', () => {
    const subway = {
      stationId: '222',
      stationName: '강남',
      lat: 37.4979,
      lng: 127.0276,
      distanceMeters: 100,
      lines: [],
      level: null,
      grade: null,
      updatedAt: null,
    }
    const renderHome = (props = {}) =>
      render(
        <HomePage
          {...baseProps}
          origin={origin}
          destination={null}
          routePanelOpen={false}
          selection={{ kind: 'subway', station: subway }}
          {...props}
        />,
      )

    it('역을 선택하면 역 카드를 보이고 대여소 카드·최근 경로는 숨긴다', () => {
      renderHome()
      expect(screen.getByRole('region', { name: '선택한 역' })).toBeTruthy()
      expect(screen.queryByRole('region', { name: '선택한 따릉이 대여소' })).toBeNull()
      expect(screen.queryByText('최근 경로')).toBeNull()
    })

    it('닫기를 누르면 clearSelection을 호출한다', () => {
      const clearSelection = vi.fn()
      renderHome({ clearSelection })
      fireEvent.click(screen.getByRole('button', { name: '역 정보 닫기' }))
      expect(clearSelection).toHaveBeenCalledOnce()
    })

    it('도착지 설정이 받아들여지면 길찾기 후 선택을 해제한다', () => {
      const findRoutes = vi.fn(() => true)
      const clearSelection = vi.fn()
      renderHome({ findRoutes, clearSelection })
      fireEvent.click(screen.getByRole('button', { name: '역 도착 설정' }))
      expect(findRoutes).toHaveBeenCalledWith({ id: 'station:222:default' })
      expect(clearSelection).toHaveBeenCalledOnce()
    })

    it('대여소를 선택하면 대여소 카드를 보인다', () => {
      renderHome({
        selection: {
          kind: 'bike',
          place: {
            id: 'bike-station:ST-1',
            name: '강남역 1번출구',
            address: '서울',
            kind: '따릉이 대여소',
            lat: 37.5,
            lng: 127,
          },
        },
      })
      expect(screen.getByRole('region', { name: '선택한 따릉이 대여소' })).toBeTruthy()
      expect(screen.queryByRole('region', { name: '선택한 역' })).toBeNull()
    })
  })
})
