import { useState } from 'react'
import { ArrowLeft, MapPin, Search, X } from 'lucide-react'
import type { Place } from '../features/route/types'
import type { Navigate } from '../app/useNavigation'
import { usePlaceSearch } from '../features/route/usePlaceSearch'
interface Props {
  searchTarget: 'origin' | 'destination'
  go: Navigate
  choosePlace: (place: Place) => void
}
export default function SearchPage({ searchTarget, go, choosePlace }: Props) {
  const [query, setQuery] = useState('')
  const { places, loading, error } = usePlaceSearch(query)
  return (
    <section className="search-screen">
      <header className="row">
        <button className="icon-button" aria-label="홈으로 돌아가기" onClick={() => go('home')}>
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
      <p className="section-label">{query ? '검색 결과' : '추천 장소'}</p>
      <div className="place-list">
        {places.map((place) => (
          <button key={place.id} onClick={() => choosePlace(place)}>
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
      </div>
      {!loading && !error && !places.length && (
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
