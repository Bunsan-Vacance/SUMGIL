import { useState } from 'react'
import { ArrowLeft, Bike, LocateFixed, MapPin, Search, Star, Trash2, X } from 'lucide-react'
import type { Place, SearchTarget } from '../features/route/types'
import { isRegisterablePlace } from '../features/route/favoritePlaces'
import type { FavoritePlace } from '../features/route/favoritePlaces'
import MapPlacePicker from '../features/map/MapPlacePicker'
import { useCurrentLocation } from '../features/map/useCurrentLocation'
import { useScrollbarVisibility } from '../components/useScrollbarVisibility'
import {
  clearRecentPlaces,
  loadRecentPlaces,
  removeRecentPlace,
  saveRecentPlace,
} from '../features/route/recentPlaces'
import {
  stationSearchResultToPlace,
  useStationSearch,
  usePlaceSearch,
} from '../features/route/usePlaceSearch'
interface Props {
  searchTarget: SearchTarget
  cancelSearch: () => void
  choosePlace: (place: Place) => boolean | void
  favorites: FavoritePlace[]
  isFavorite: (id: string) => boolean
  toggleFavorite: (place: Place) => void
}

const searchTitles: Record<SearchTarget, string> = {
  origin: '출발지 검색',
  destination: '도착지 검색',
  home: '집 등록',
  work: '회사 등록',
}
const favoriteLabelNames = { home: '집', work: '회사' } as const

export default function SearchPage({
  searchTarget,
  cancelSearch,
  choosePlace,
  favorites,
  isFavorite,
  toggleFavorite,
}: Props) {
  const searchRef = useScrollbarVisibility<HTMLElement>()
  const [query, setQuery] = useState('')
  const [recentPlaces, setRecentPlaces] = useState<Place[]>(loadRecentPlaces)
  const [mapMode, setMapMode] = useState(false)
  const [locationMessage, setLocationMessage] = useState('')
  const { places, loading, error } = usePlaceSearch(mapMode ? '' : query)
  const {
    stations,
    loading: stationsLoading,
    error: stationsError,
  } = useStationSearch(mapMode ? '' : query)
  const searchPlaces = [...stations.map(stationSearchResultToPlace), ...places]
  const selectPlace = (place: Place, save = true) => {
    const accepted = choosePlace(place)
    if (accepted !== false && save) setRecentPlaces(saveRecentPlace(place))
    return accepted
  }
  const renderPlaceButton = (place: Place, kind: string) => (
    <button onClick={() => selectPlace(place)}>
      <span className="place-icon">
        {place.kind === '따릉이 대여소' ? <Bike size={20} /> : <MapPin size={20} />}
      </span>
      <span>
        <strong>{place.name}</strong>
        <small>{place.address}</small>
      </span>
      <small>{kind}</small>
    </button>
  )
  const renderFavoriteToggle = (place: Place) => {
    if (!isRegisterablePlace(place)) return null
    const favorite = isFavorite(place.id)
    return (
      <button
        className="icon-button"
        aria-label={`${place.name} 즐겨찾기 ${favorite ? '해제' : '추가'}`}
        aria-pressed={favorite}
        onClick={() => toggleFavorite(place)}
      >
        <Star size={16} fill={favorite ? 'currentColor' : 'none'} />
      </button>
    )
  }
  const showSavedLists = !query.trim()
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
    <section ref={searchRef} className="search-screen scrollbar-auto">
      <header className="row">
        <button className="icon-button" aria-label="이전 화면으로 돌아가기" onClick={cancelSearch}>
          <ArrowLeft />
        </button>
        <h2>{searchTitles[searchTarget]}</h2>
      </header>
      <label className="search-input">
        <Search size={20} />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
              event.currentTarget.blur()
            }
          }}
          enterKeyHint="done"
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
      {query.trim() ? (
        <p className="section-label">검색 결과</p>
      ) : (
        !favorites.length &&
        !recentPlaces.length && <p className="section-label">검색어를 입력해 장소를 찾아보세요</p>
      )}
      {showSavedLists && favorites.length > 0 && (
        <>
          <p className="section-label">즐겨찾기</p>
          <div className="place-list">
            {favorites.map(({ place, label }) => (
              <div className="place-row favorite-place" key={place.id}>
                {renderPlaceButton(place, label ? favoriteLabelNames[label] : place.kind)}
                {renderFavoriteToggle(place)}
              </div>
            ))}
          </div>
        </>
      )}
      {showSavedLists && recentPlaces.length > 0 && <p className="section-label">최근 검색</p>}
      <div className="place-list">
        {searchPlaces.map((place) => (
          <div className="place-row" key={place.id}>
            {renderPlaceButton(place, place.kind)}
            {renderFavoriteToggle(place)}
          </div>
        ))}
        {showSavedLists &&
          recentPlaces.map((place) => (
            <div className="place-row recent-place" key={place.id}>
              {renderPlaceButton(place, place.kind)}
              {renderFavoriteToggle(place)}
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
      {!query.trim() && !favorites.length && !recentPlaces.length && (
        <div className="empty">
          <Search />
          <h3>검색어를 입력해 주세요</h3>
          <p>장소 이름이나 도로명 주소로 검색할 수 있어요.</p>
        </div>
      )}
      {query.trim() &&
        !loading &&
        !stationsLoading &&
        !error &&
        !stationsError &&
        !searchPlaces.length && (
          <div className="empty">
            <Search />
            <h3>검색 결과가 없어요</h3>
            <p>다른 장소, 역, 주소로 검색해 주세요.</p>
          </div>
        )}
      {(loading || stationsLoading) && (
        <p role="status" className="section-label">
          검색 중…
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {stationsError && (
        <p role="alert" className="error">
          {stationsError}
        </p>
      )}
    </section>
  )
}
