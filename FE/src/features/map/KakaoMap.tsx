import { Bike, LocateFixed, RotateCw, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { Place } from '../route/types'
import { useKakaoMap } from './useKakaoMap'
import { useCurrentLocation } from './useCurrentLocation'
export default function KakaoMap({
  origin,
  destination,
  places,
  onMessage,
  onPlaceSelect,
  showPlaceInfo = true,
  focusedPlace,
}: {
  origin?: Place | null
  destination?: Place | null
  places?: Place[]
  onMessage: (message: string) => void
  onPlaceSelect?: (place: Place) => void
  showPlaceInfo?: boolean
  focusedPlace?: Place | null
}) {
  const [selectedPlace, setSelectedPlace] = useState<Place | null>(null)
  const routePlaces = useMemo(
    () => [origin, destination].filter((place): place is Place => Boolean(place)),
    [origin, destination],
  )
  const mapPlaces = places ?? routePlaces
  const mapFocus = focusedPlace === undefined ? selectedPlace : focusedPlace
  const selectPlace = (place: Place) => {
    setSelectedPlace(place)
    onPlaceSelect?.(place)
  }
  const { container, status, retry, showPosition, locationScope } = useKakaoMap(
    origin ?? null,
    destination ?? null,
    onMessage,
    selectPlace,
    mapPlaces,
    mapFocus,
    places === undefined ? null : mapFocus,
  )
  const { locating, locate } = useCurrentLocation(showPosition, onMessage, locationScope)
  useEffect(() => {
    setSelectedPlace(null)
  }, [origin, destination, places])
  useEffect(() => {
    if (!selectedPlace) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedPlace(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [selectedPlace])
  return (
    <div className="kakao-map-wrap">
      <div ref={container} className="kakao-map-canvas" aria-label="카카오 지도" />
      {status !== 'ready' && (
        <div className="map-state" role="status">
          <p>{status === 'loading' ? '지도를 불러오고 있어요' : '지도를 불러오지 못했어요'}</p>
          {status === 'error' && (
            <button className="secondary" onClick={retry}>
              <RotateCw size={15} />
              다시 시도
            </button>
          )}
        </div>
      )}
      <div
        className={`map-bottom-controls${showPlaceInfo && selectedPlace ? ' has-place-info' : ''}`}
      >
        {status === 'ready' && (
          <button
            className="icon-button kakao-locate"
            aria-label="현재 위치"
            disabled={locating}
            onClick={locate}
          >
            {locating ? <span className="spinner" /> : <LocateFixed />}
          </button>
        )}
        {showPlaceInfo && selectedPlace && (
          <section
            className="map-place-info"
            role="region"
            aria-label="선택한 장소 정보"
            aria-live="polite"
          >
            <div>
              <div className="map-place-info-title">
                {selectedPlace.kind === '따릉이 대여소' && (
                  <span className="bike-station-info-icon">
                    <Bike size={15} />
                  </span>
                )}
                <strong>{selectedPlace.name}</strong>
              </div>
              <p>{selectedPlace.address}</p>
            </div>
            <button
              className="icon-button"
              aria-label="장소 정보 닫기"
              onClick={() => setSelectedPlace(null)}
            >
              <X size={17} />
            </button>
          </section>
        )}
      </div>
      {showPlaceInfo && (
        <div className="map-place-shortcuts" aria-label="지도 장소 정보">
          {origin && (
            <button type="button" onClick={() => selectPlace(origin)}>
              출발 장소 정보
            </button>
          )}
          {destination && (
            <button type="button" onClick={() => selectPlace(destination)}>
              도착 장소 정보
            </button>
          )}
        </div>
      )}
    </div>
  )
}
