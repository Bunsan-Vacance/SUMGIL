import { useState } from 'react'
import { ArrowLeft, LocateFixed, MapPin, Search, Trash2, X } from 'lucide-react'
import type { Place } from '../features/route/types'
import MapPlacePicker from '../features/map/MapPlacePicker'
import { useCurrentLocation } from '../features/map/useCurrentLocation'
import {
  clearRecentPlaces,
  loadRecentPlaces,
  removeRecentPlace,
  saveRecentPlace,
  usePlaceSearch,
} from '../features/route/usePlaceSearch'
interface Props {
  searchTarget: 'origin' | 'destination'
  cancelSearch: () => void
  choosePlace: (place: Place) => boolean | void
}
export default function SearchPage({ searchTarget, cancelSearch, choosePlace }: Props) {
  const [query, setQuery] = useState('')
  const [recentPlaces, setRecentPlaces] = useState<Place[]>(loadRecentPlaces)
  const [mapMode, setMapMode] = useState(false)
  const [locationMessage, setLocationMessage] = useState('')
  const { places, loading, error } = usePlaceSearch(mapMode ? '' : query)
  const selectPlace = (place: Place, save = true) => {
    const accepted = choosePlace(place)
    if (accepted !== false && save) setRecentPlaces(saveRecentPlace(place))
    return accepted
  }
  const { locating, locate } = useCurrentLocation(
    (position) => {
      const { latitude, longitude } = position.coords
      if (
        !Number.isFinite(latitude) ||
        !Number.isFinite(longitude) ||
        latitude < -90 ||
        latitude > 90 ||
        longitude < -180 ||
        longitude > 180
      ) {
        setLocationMessage('현재 위치를 확인하지 못했어요. 다시 시도해 주세요.')
        return
      }
      selectPlace(
        {
          id: `current-location:${latitude}:${longitude}`,
          name: '현재 위치',
          address: `위도 ${latitude.toFixed(6)}, 경도 ${longitude.toFixed(6)}`,
          kind: '현재 위치',
          lat: latitude,
          lng: longitude,
        },
        false,
      )
    },
    (message) => {
      setLocationMessage(message)
    },
    `${searchTarget}-${mapMode ? 'map' : 'search'}`,
  )
  if (mapMode) {
    return (
      <MapPlacePicker
        target={searchTarget}
        onCancel={() => setMapMode(false)}
        onSelect={(place) => {
          const accepted = selectPlace(place)
          if (accepted !== false) {
            setMapMode(false)
          }
        }}
      />
    )
  }
  return (
    <section className="search-screen">
      <header className="row">
        <button className="icon-button" aria-label="이전 화면으로 돌아가기" onClick={cancelSearch}>
          <ArrowLeft />
        </button>
        <h2>{searchTarget === 'origin' ? '출발지' : '도착지'} 검색</h2>
      </header>
      <label className="search-input">
        <Search size={20} />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="장소, 역, 주소 검색"
          aria-label="장소 검색어"
        />
        {query && (
          <button className="icon-button" aria-label="검색어 지우기" onClick={() => setQuery('')}>
            <X size={18} />
          </button>
        )}
      </label>
      {searchTarget === 'origin' && (
        <>
          <button className="secondary full search-action" disabled={locating} onClick={locate}>
            {locating ? <span className="spinner" /> : <LocateFixed size={17} />}
            현재 위치에서 출발
          </button>
          {locationMessage && (
            <p role="alert" className="error">
              {locationMessage}
            </p>
          )}
        </>
      )}
      <button className="secondary full search-action" onClick={() => setMapMode(true)}>
        <MapPin size={17} />
        지도에서 선택
      </button>
      <p className="section-label">
        {query.trim()
          ? '검색 결과'
          : recentPlaces.length
            ? '최근 검색'
            : '검색어를 입력해 장소를 찾아보세요'}
      </p>
      <div className="place-list">
        {places.map((place) => (
          <button key={place.id} onClick={() => selectPlace(place)}>
            <span className="place-icon">
              <MapPin size={20} />
            </span>
            <span>
              <strong>{place.name}</strong>
              <small>{place.address}</small>
            </span>
            <small>{place.kind}</small>
          </button>
        ))}
        {!query.trim() &&
          recentPlaces.map((place) => (
            <div className="recent-place" key={place.id}>
              <button onClick={() => selectPlace(place)}>
                <span className="place-icon">
                  <MapPin size={20} />
                </span>
                <span>
                  <strong>{place.name}</strong>
                  <small>{place.address}</small>
                </span>
                <small>{place.kind}</small>
              </button>
              <button
                className="icon-button"
                aria-label={`${place.name} 최근 검색 삭제`}
                onClick={() => setRecentPlaces(removeRecentPlace(place.id))}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
      </div>
      {!query.trim() && recentPlaces.length > 0 && (
        <button
          className="text-button recent-clear"
          onClick={() => setRecentPlaces(clearRecentPlaces())}
        >
          최근 검색 전체 삭제
        </button>
      )}
      {!query.trim() && !recentPlaces.length && (
        <div className="empty">
          <Search />
          <h3>검색어를 입력해 주세요</h3>
          <p>장소 이름이나 도로명 주소로 검색할 수 있어요.</p>
        </div>
      )}
      {query.trim() && !loading && !error && !places.length && (
        <div className="empty">
          <Search />
          <h3>검색 결과가 없어요</h3>
          <p>다른 장소 이름으로 검색해 주세요.</p>
        </div>
      )}
      {loading && (
        <p role="status" className="section-label">
          검색 중…
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </section>
  )
}
