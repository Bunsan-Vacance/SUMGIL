import { ArrowLeft, Bike, MapPin, Search, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import BottomSheet from '../components/BottomSheet'
import KakaoMap from '../features/map/KakaoMap'
import { usePlaceSearch } from '../features/route/usePlaceSearch'
import type { Place } from '../features/route/types'

interface Props {
  onBack: () => void
  onMessage: (message: string) => void
  setOrigin: (place: Place) => boolean | void
  findRoutes: (place: Place) => boolean | void
}

function PlaceInfoCard({
  place,
  onClose,
  onSetOrigin,
  onSetDestination,
}: {
  place: Place
  onClose: () => void
  onSetOrigin: (place: Place) => void
  onSetDestination: (place: Place) => void
}) {
  return (
    <section className="browse-place-card" aria-label="선택한 장소" aria-live="polite">
      <div className="browse-place-heading">
        <div>
          <small className="browse-place-kind">{place.kind}</small>
          <strong>{place.name}</strong>
          <p>{place.address}</p>
        </div>
        <button className="icon-button" aria-label="장소 정보 닫기" onClick={onClose}>
          <X size={17} />
        </button>
      </div>
      <div className="browse-place-actions">
        <button className="secondary" onClick={() => onSetOrigin(place)}>
          출발지로 설정
        </button>
        <button className="primary" onClick={() => onSetDestination(place)}>
          도착지로 설정
        </button>
      </div>
    </section>
  )
}

export default function BrowsePage({ onBack, onMessage, setOrigin, findRoutes }: Props) {
  const browseRef = useRef<HTMLElement>(null)
  const toolbarRef = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [selectedPlace, setSelectedPlace] = useState<Place | null>(null)
  const { places, loading, error } = usePlaceSearch(query)

  useLayoutEffect(() => {
    const browse = browseRef.current
    const toolbar = toolbarRef.current
    if (!browse || !toolbar) return
    const updateToolbarHeight = () => {
      browse.style.setProperty('--browse-toolbar-height', `${toolbar.offsetHeight}px`)
    }
    updateToolbarHeight()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(updateToolbarHeight)
    observer.observe(toolbar)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    setSelectedPlace(null)
  }, [query])
  useEffect(() => {
    if (!selectedPlace) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedPlace(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [selectedPlace])

  const chooseOrigin = (place: Place) => {
    if (setOrigin(place) !== false) setSelectedPlace(null)
  }
  const chooseDestination = (place: Place) => {
    if (findRoutes(place) !== false) setSelectedPlace(null)
  }

  return (
    <section ref={browseRef} className="browse-screen">
      <KakaoMap
        origin={null}
        destination={null}
        places={places}
        onMessage={onMessage}
        onPlaceSelect={setSelectedPlace}
        focusedPlace={selectedPlace}
        showPlaceInfo={false}
      />
      <div ref={toolbarRef} className="browse-toolbar">
        <header className="row browse-header">
          <button className="icon-button" aria-label="홈으로 돌아가기" onClick={onBack}>
            <ArrowLeft />
          </button>
          <div>
            <h2>장소 탐색</h2>
            <p>장소를 찾아 출발지나 도착지로 설정할 수 있어요.</p>
          </div>
        </header>
        <label className="search-input browse-input">
          <Search size={20} />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="장소, 역, 주소 검색"
            aria-label="탐색할 장소 검색어"
          />
          {query && (
            <button className="icon-button" aria-label="검색어 지우기" onClick={() => setQuery('')}>
              <X size={18} />
            </button>
          )}
        </label>
      </div>
      <BottomSheet
        ariaLabel="장소 탐색 결과"
        initialSnap="collapsed"
        preferredSnap={
          selectedPlace ? 'collapsed' : query.trim() && places.length ? 'default' : 'collapsed'
        }
      >
        {selectedPlace ? (
          <PlaceInfoCard
            place={selectedPlace}
            onClose={() => setSelectedPlace(null)}
            onSetOrigin={chooseOrigin}
            onSetDestination={chooseDestination}
          />
        ) : (
          <div className="browse-results">
            <p className="section-label">
              {query.trim() ? `${places.length}개 장소` : '장소 이름이나 주소를 검색해 보세요'}
            </p>
            {loading && (
              <p role="status" className="browse-state">
                검색 중…
              </p>
            )}
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            {!loading && !error && query.trim() && !places.length && (
              <div className="empty browse-empty">
                <Search />
                <h3>검색 결과가 없어요</h3>
                <p>다른 장소 이름으로 검색해 주세요.</p>
              </div>
            )}
            {!query.trim() && !loading && (
              <div className="empty browse-empty">
                <MapPin />
                <h3>찾고 싶은 장소를 검색해 주세요</h3>
                <p>검색 결과를 누르면 지도에서 위치를 확인할 수 있어요.</p>
              </div>
            )}
            {places.length > 0 && (
              <div className="place-list browse-place-list">
                {places.map((place) => (
                  <button
                    key={place.id}
                    className="browse-place-result"
                    aria-pressed={false}
                    onClick={() => setSelectedPlace(place)}
                  >
                    <span className="place-icon">
                      {place.kind === '따릉이 대여소' ? <Bike size={20} /> : <MapPin size={20} />}
                    </span>
                    <span>
                      <strong>{place.name}</strong>
                      <small>{place.address}</small>
                    </span>
                    <small>{place.kind}</small>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </BottomSheet>
    </section>
  )
}
