import { ArrowDownUp, ArrowRight, Briefcase, Home, Pencil, Search, Star } from 'lucide-react'
import type { Place } from '../features/route/types'
import type { FavoriteLabel, FavoritePlace } from '../features/route/favoritePlaces'

const EXTRA_CHIP_LIMIT = 5

interface Props {
  origin: Place
  destination: Place | null
  openSearch: (target: 'origin' | 'destination') => void
  routePanelOpen: boolean
  toggleRoutePanel: () => void
  findRoutes: (place?: Place) => boolean | void
  swapPlaces: () => void
  favorites: FavoritePlace[]
  home: FavoritePlace | null
  work: FavoritePlace | null
  openFavoriteRegistration: (label: FavoriteLabel) => void
}
export default function HomePage({
  origin,
  destination,
  openSearch,
  routePanelOpen,
  toggleRoutePanel,
  findRoutes,
  swapPlaces,
  favorites,
  home,
  work,
  openFavoriteRegistration,
}: Props) {
  const extraFavorites = favorites.filter((item) => item.label === null).slice(0, EXTRA_CHIP_LIMIT)
  return (
    <>
      <div className="home-topbar" hidden={routePanelOpen}>
        <button
          type="button"
          className="primary home-route-button"
          aria-expanded={routePanelOpen}
          aria-controls="home-route-panel"
          onClick={toggleRoutePanel}
        >
          길찾기
          <ArrowRight size={16} />
        </button>
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
        <button type="button" className="primary" onClick={() => findRoutes()}>
          경로 찾기
          <ArrowRight size={18} />
        </button>
      </section>
    </>
  )
}
