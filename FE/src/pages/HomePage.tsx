import { useState } from 'react'
import {
  ArrowDownUp,
  ArrowRight,
  Briefcase,
  Clock,
  Home,
  Pencil,
  Search,
  Star,
  Trash2,
} from 'lucide-react'
import BottomSheet from '../components/BottomSheet'
import HomeLayerLegend from '../features/map/HomeLayerLegend'
import HomeLayerToggle from '../features/map/HomeLayerToggle'
import { availableLayers } from '../features/map/homeLayers'
import type { HomeLayer } from '../features/map/homeLayers'
import {
  formatSearchedAt,
  loadRecentRoutes,
  removeRecentRoute,
} from '../features/route/recentRoutes'
import type { Place } from '../features/route/types'
import type { FavoriteLabel, FavoritePlace } from '../features/route/favoritePlaces'

const EXTRA_CHIP_LIMIT = 5
const RECENT_ROUTE_DISPLAY_LIMIT = 5

interface Props {
  origin: Place
  destination: Place | null
  openSearch: (target: 'origin' | 'destination') => void
  routePanelOpen: boolean
  toggleRoutePanel: () => void
  findRoutes: (place?: Place) => boolean | void
  findRoutesFrom: (origin: Place, destination: Place) => boolean | void
  swapPlaces: () => void
  favorites: FavoritePlace[]
  home: FavoritePlace | null
  work: FavoritePlace | null
  openFavoriteRegistration: (label: FavoriteLabel) => void
  layer: HomeLayer | null
  setLayer: (layer: HomeLayer | null) => void
}
export default function HomePage({
  origin,
  destination,
  openSearch,
  routePanelOpen,
  toggleRoutePanel,
  findRoutes,
  findRoutesFrom,
  swapPlaces,
  favorites,
  home,
  work,
  openFavoriteRegistration,
  layer,
  setLayer,
}: Props) {
  const [recentRoutes, setRecentRoutes] = useState(loadRecentRoutes)
  const extraFavorites = favorites.filter((item) => item.label === null).slice(0, EXTRA_CHIP_LIMIT)
  const placeLabel = (place: Place | null) => {
    if (!place) return '현재 위치'
    if (home?.place.id === place.id) return '집'
    if (work?.place.id === place.id) return '회사'
    return place.name
  }
  return (
    <>
      <div className="home-topbar" hidden={routePanelOpen}>
        <div className="home-search-bar">
          <button type="button" aria-label="도착지 검색" onClick={() => openSearch('destination')}>
            <Search size={18} />
            <span>어디로 갈까요?</span>
          </button>
          <button
            type="button"
            className="primary home-route-button"
            aria-expanded={routePanelOpen}
            aria-controls="home-route-panel"
            onClick={toggleRoutePanel}
          >
            길찾기
          </button>
        </div>
        <div className="home-chips" role="group" aria-label="자주 가는 곳">
          <button
            type="button"
            className={home ? 'home-chip' : 'home-chip unset'}
            aria-label={home ? '집으로 길찾기' : '집 등록'}
            onClick={() => (home ? findRoutes(home.place) : openFavoriteRegistration('home'))}
          >
            <Home size={15} />집
          </button>
          <button
            type="button"
            className={work ? 'home-chip' : 'home-chip unset'}
            aria-label={work ? '회사로 길찾기' : '회사 등록'}
            onClick={() => (work ? findRoutes(work.place) : openFavoriteRegistration('work'))}
          >
            <Briefcase size={15} />
            회사
          </button>
          {extraFavorites.map(({ place }) => (
            <button
              key={place.id}
              type="button"
              className="home-chip"
              aria-label={`${place.name} 길찾기`}
              onClick={() => findRoutes(place)}
            >
              <Star size={15} />
              {place.name}
            </button>
          ))}
        </div>
        <HomeLayerLegend layer={layer} />
        <HomeLayerToggle layers={availableLayers} active={layer} onChange={setLayer} />
      </div>
      <section
        id="home-route-panel"
        className="home-panel"
        aria-label="길찾기 입력"
        hidden={!routePanelOpen}
      >
        <div className="home-panel-heading">
          <h2>어디로 갈까요?</h2>
        </div>
        <div className="trip-fields">
          <button
            type="button"
            className="swap-button"
            aria-label="출발지와 도착지 교환"
            disabled={!destination || !origin.name}
            onClick={swapPlaces}
          >
            <ArrowDownUp size={19} />
          </button>
          <div className="trip-field-values">
            <button type="button" onClick={() => openSearch('origin')}>
              <span className="dot start" />
              <small>출발</small>
              <strong className={!origin.name ? 'muted' : ''}>
                {origin.name || '출발지를 검색하세요'}
              </strong>
              <Pencil size={16} />
            </button>
            <button type="button" onClick={() => openSearch('destination')}>
              <span className="dot end" />
              <small>도착</small>
              <strong className={!destination ? 'muted' : ''}>
                {destination?.name || '도착지를 검색하세요'}
              </strong>
              <Search size={17} />
            </button>
          </div>
        </div>
        <button type="button" className="primary" onClick={() => findRoutes()}>
          경로 찾기
          <ArrowRight size={18} />
        </button>
      </section>
      <BottomSheet ariaLabel="홈 정보" className="home-sheet" initialSnap="default">
        <h2 className="home-sheet-title">최근 경로</h2>
        {recentRoutes.length === 0 ? (
          <p className="home-sheet-empty">아직 찾은 경로가 없어요</p>
        ) : (
          <ul className="home-recent-routes">
            {recentRoutes.slice(0, RECENT_ROUTE_DISPLAY_LIMIT).map((route) => {
              const title = `${placeLabel(route.origin)} → ${placeLabel(route.destination)}`
              return (
                <li
                  className={route.pinned ? 'home-recent-route pinned' : 'home-recent-route'}
                  key={route.id}
                >
                  <button
                    type="button"
                    aria-label={`${title} ${route.pinned ? '저장한 ' : ''}경로 찾기`}
                    onClick={() =>
                      route.origin
                        ? findRoutesFrom(route.origin, route.destination)
                        : findRoutes(route.destination)
                    }
                  >
                    {route.pinned ? <Star size={18} fill="currentColor" /> : <Clock size={18} />}
                    <span>
                      <strong>{title}</strong>
                      <small>{formatSearchedAt(route.searchedAt)}</small>
                    </span>
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`${title} 최근 경로 삭제`}
                    onClick={() => setRecentRoutes(removeRecentRoute(route.id))}
                  >
                    <Trash2 size={16} />
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </BottomSheet>
    </>
  )
}
