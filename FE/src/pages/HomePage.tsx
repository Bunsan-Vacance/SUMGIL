import { ArrowDownUp, ArrowLeft, ArrowRight, Pencil, Search } from 'lucide-react'
import type { Place } from '../features/route/types'
interface Props {
  origin: Place
  destination: Place | null
  openSearch: (target: 'origin' | 'destination') => void
  routePanelOpen: boolean
  toggleRoutePanel: () => void
  closeRoutePanel: () => void
  findRoutes: () => void
  swapPlaces: () => void
}
export default function HomePage({
  origin,
  destination,
  openSearch,
  routePanelOpen,
  toggleRoutePanel,
  closeRoutePanel,
  findRoutes,
  swapPlaces,
}: Props) {
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
          <button
            type="button"
            className="icon-button home-panel-back"
            aria-label="홈으로 돌아가기"
            onClick={closeRoutePanel}
          >
            <ArrowLeft size={19} />
          </button>
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
    </>
  )
}
