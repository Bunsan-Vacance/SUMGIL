import { Bike, LocateFixed, RotateCw, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import BottomSheet from '../../components/BottomSheet'
import { bikeStockRepository } from '../../api/repositories'
import type { BikeStock } from '../../api/contracts'
import { isCongestionPreview } from '../../app/preview'
import type { Place, Route } from '../route/types'
import {
  SEGMENT_CONGESTION_LEVELS,
  segmentCongestionPresentation,
  withSegmentCongestionPreview,
} from '../route/segmentCongestion'
import { useKakaoMap } from './useKakaoMap'
import { useCurrentLocation } from './useCurrentLocation'

function bikeRentalId(place: Place) {
  if (place.rentalId) return place.rentalId
  if (place.id.startsWith('bike-station:')) return place.id.slice('bike-station:'.length)
  return undefined
}

function stockUpdatedLabel(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isFinite(date.getTime())
    ? date.toLocaleTimeString('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour: '2-digit',
        minute: '2-digit',
      })
    : value
}

function congestionPreviewPoint(
  coordinate: [number, number],
  bounds: { minLng: number; maxLng: number; minLat: number; maxLat: number },
) {
  const width = 390
  const height = 520
  const padding = 34
  const x =
    padding +
    ((coordinate[0] - bounds.minLng) / (bounds.maxLng - bounds.minLng || 1)) * (width - padding * 2)
  const y =
    padding +
    ((bounds.maxLat - coordinate[1]) / (bounds.maxLat - bounds.minLat || 1)) *
      (height - padding * 2)
  return `${x.toFixed(1)},${y.toFixed(1)}`
}

function CongestionPreviewMap({ route }: { route: Route }) {
  const entries = route.legs.flatMap((leg) =>
    (leg.geometry?.coordinates || []).map((coordinates) => ({ leg, coordinates })),
  )
  const points = entries.flatMap(({ coordinates }) => coordinates)
  if (!points.length) return null
  const bounds = {
    minLng: Math.min(...points.map(([lng]) => lng)),
    maxLng: Math.max(...points.map(([lng]) => lng)),
    minLat: Math.min(...points.map(([, lat]) => lat)),
    maxLat: Math.max(...points.map(([, lat]) => lat)),
  }
  const point = (coordinate: [number, number]) => congestionPreviewPoint(coordinate, bounds)
  const endpointPoints = entries.flatMap(({ leg, coordinates }) => {
    const first = coordinates[0]
    const last = coordinates.at(-1)
    if (!first || !last) return []
    return [
      { leg, coordinate: first },
      { leg, coordinate: last },
    ]
  })
  const labels = [
    { label: '출발', coordinate: endpointPoints[0]?.coordinate },
    ...route.legs
      .filter((leg) => leg.transfer)
      .map((leg) => ({ label: '환승', coordinate: leg.geometry?.coordinates[0]?.[0] })),
    { label: '도착', coordinate: endpointPoints.at(-1)?.coordinate },
  ].filter(
    (marker): marker is { label: string; coordinate: [number, number] } => !!marker.coordinate,
  )

  return (
    <div className="congestion-preview-map" data-preview="congestion">
      <svg viewBox="0 0 390 520" role="img" aria-label="혼잡도 경로 시안 지도">
        <rect width="390" height="520" fill="#e9eee8" />
        <path className="congestion-preview-road" d="M-20 120 410 430 M-20 430 410 100" />
        <path className="congestion-preview-road secondary" d="M90 -20 300 540 M280 -20 80 540" />
        {entries.map(({ leg, coordinates }, index) => {
          const points = coordinates.map(point).join(' ')
          const congestion = segmentCongestionPresentation(leg.segmentCongestionGrade)
          const color = congestion?.color || '#708078'
          return (
            <g key={`${leg.title}-${index}`}>
              <polyline className="congestion-preview-casing" points={points} />
              <polyline
                className="congestion-preview-line"
                data-grade={leg.segmentCongestionGrade || 'NEUTRAL'}
                points={points}
                stroke={color}
                strokeDasharray={leg.transfer ? '8 7' : undefined}
              />
            </g>
          )
        })}
        {labels.map(({ label, coordinate }, index) => (
          <g key={`${label}-${index}`} className="congestion-preview-marker">
            <circle
              cx={point(coordinate).split(',')[0]}
              cy={point(coordinate).split(',')[1]}
              r="7"
            />
            <text x={point(coordinate).split(',')[0]} y={point(coordinate).split(',')[1]} dy="-12">
              {label}
            </text>
          </g>
        ))}
        <text className="congestion-preview-caption" x="16" y="500">
          시안 지도 · 카카오 지도 연결 전
        </text>
      </svg>
    </div>
  )
}

function BikeStockSheet({
  station,
  state,
  stock,
  onClose,
  onRetry,
}: {
  station: Place
  state: 'loading' | 'success' | 'error' | 'unavailable'
  stock: BikeStock | null
  onClose: () => void
  onRetry: () => void
}) {
  return (
    <BottomSheet
      key={station.id}
      initialSnap="collapsed"
      preferredSnap="collapsed"
      className="map-bike-stock-sheet"
      ariaLabel="따릉이 실시간 재고"
    >
      <section className="bike-stock-sheet" aria-live="polite">
        <header className="bike-stock-heading">
          <div className="bike-stock-title">
            <span className="bike-station-info-icon">
              <Bike size={15} />
            </span>
            <div>
              <h2>{station.name}</h2>
            </div>
          </div>
          <button className="icon-button" aria-label="재고 정보 닫기" onClick={onClose}>
            <X size={17} />
          </button>
        </header>
        {(station.dockCount !== undefined || station.distanceMeters !== undefined) && (
          <div className="bike-stock-meta">
            {station.dockCount !== undefined && <span>거치대 총 {station.dockCount}개</span>}
            {station.distanceMeters !== undefined && (
              <span>조회한 지도 중심에서 {Math.round(station.distanceMeters)}m</span>
            )}
          </div>
        )}
        {state === 'loading' && (
          <p className="bike-stock-state" role="status">
            실시간 재고를 확인하고 있어요…
          </p>
        )}
        {state === 'error' && (
          <div className="bike-stock-state" role="alert">
            <p>재고 정보를 불러오지 못했어요.</p>
            <button className="secondary" onClick={onRetry}>
              다시 시도
            </button>
          </div>
        )}
        {state === 'unavailable' && (
          <p className="bike-stock-state" role="status">
            현재 실시간 재고를 확인할 수 없어요.
          </p>
        )}
        {state === 'success' && stock && (
          <div className={`bike-stock-result bike-stock-${stock.status.toLowerCase()}`}>
            {stock.status === 'AVAILABLE' && stock.availableBikes !== null ? (
              <div className="bike-stock-summary">
                <strong>{stock.availableBikes}대</strong>
                <p>
                  {stock.availableBikes === 0
                    ? '대여 가능한 자전거가 없어요.'
                    : '현재 대여할 수 있어요.'}
                </p>
              </div>
            ) : stock.status === 'STALE' && stock.availableBikes !== null ? (
              <div className="bike-stock-summary">
                <strong>{stock.availableBikes}대</strong>
                <p>마지막 확인 재고예요. 최신 정보가 아닐 수 있어요.</p>
              </div>
            ) : (
              <p>현재 실시간 재고를 확인할 수 없어요.</p>
            )}
            {stockUpdatedLabel(stock.stockUpdatedAt) && (
              <small>마지막 확인 {stockUpdatedLabel(stock.stockUpdatedAt)}</small>
            )}
          </div>
        )}
      </section>
    </BottomSheet>
  )
}

export default function KakaoMap({
  origin,
  destination,
  places,
  onMessage,
  onPlaceSelect,
  showPlaceInfo = true,
  focusedPlace,
  route,
}: {
  origin?: Place | null
  destination?: Place | null
  places?: Place[]
  onMessage: (message: string) => void
  onPlaceSelect?: (place: Place) => void
  showPlaceInfo?: boolean
  focusedPlace?: Place | null
  route?: Route | null
}) {
  const [selectedPlace, setSelectedPlace] = useState<Place | null>(null)
  const [bikeStationsVisible, setBikeStationsVisible] = useState(true)
  const [bikeStockStation, setBikeStockStation] = useState<Place | null>(null)
  const [bikeStock, setBikeStock] = useState<BikeStock | null>(null)
  const [bikeStockState, setBikeStockState] = useState<
    'loading' | 'success' | 'error' | 'unavailable'
  >('unavailable')
  const stockRequestIdRef = useRef(0)
  const stockAbortRef = useRef<AbortController | null>(null)
  const routePlaces = useMemo(
    () => [origin, destination].filter((place): place is Place => Boolean(place)),
    [origin, destination],
  )
  const mapPlaces = places ?? routePlaces
  const mapFocus = focusedPlace === undefined ? selectedPlace : focusedPlace
  const showSelectedPlaceInfo = showPlaceInfo && selectedPlace
  const effectiveRoute = useMemo(() => {
    if (!route) return null
    return {
      ...route,
      legs: withSegmentCongestionPreview(route.legs),
    }
  }, [route])
  const closeBikeStock = () => {
    stockAbortRef.current?.abort()
    stockAbortRef.current = null
    stockRequestIdRef.current += 1
    setBikeStockStation(null)
    setBikeStock(null)
    setBikeStockState('unavailable')
    setSelectedPlace(null)
  }
  const selectBikeStation = (place: Place) => {
    stockAbortRef.current?.abort()
    const requestId = ++stockRequestIdRef.current
    setBikeStockStation(place)
    setSelectedPlace(place)
    setBikeStock(null)
    setBikeStockState('loading')
    const rentalId = bikeRentalId(place)
    if (!bikeStockRepository || !rentalId) {
      setBikeStockState('unavailable')
      return
    }
    const controller = new AbortController()
    stockAbortRef.current = controller
    bikeStockRepository
      .stock(rentalId, controller.signal)
      .then((value) => {
        if (controller.signal.aborted || requestId !== stockRequestIdRef.current) return
        setBikeStock(value)
        setBikeStockState('success')
      })
      .catch(() => {
        if (controller.signal.aborted || requestId !== stockRequestIdRef.current) return
        setBikeStockState('error')
      })
  }
  const selectPlace = (place: Place) => {
    if (place.kind === '따릉이 대여소') {
      selectBikeStation(place)
      onPlaceSelect?.(place)
      return
    }
    if (bikeStockStation) closeBikeStock()
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
    effectiveRoute,
    bikeStationsVisible,
  )
  const { locating, locate } = useCurrentLocation(showPosition, onMessage, locationScope)
  const showCongestionPreview =
    status !== 'ready' && Boolean(effectiveRoute) && isCongestionPreview(location.search)
  useEffect(() => {
    setSelectedPlace(null)
    closeBikeStock()
  }, [origin, destination, places])
  useEffect(() => {
    if (!selectedPlace) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') bikeStockStation ? closeBikeStock() : setSelectedPlace(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [selectedPlace, bikeStockStation])
  useEffect(() => () => stockAbortRef.current?.abort(), [])
  return (
    <div className="kakao-map-wrap">
      <div ref={container} className="kakao-map-canvas" aria-label="카카오 지도" />
      {showCongestionPreview && effectiveRoute && <CongestionPreviewMap route={effectiveRoute} />}
      <button
        type="button"
        className="map-bike-toggle"
        aria-label={bikeStationsVisible ? '따릉이 대여소 숨기기' : '따릉이 대여소 보이기'}
        aria-pressed={bikeStationsVisible}
        title={bikeStationsVisible ? '따릉이 대여소 숨기기' : '따릉이 대여소 보이기'}
        onClick={() => setBikeStationsVisible((visible) => !visible)}
      >
        <span className="map-bike-toggle-thumb" aria-hidden="true">
          <Bike size={14} strokeWidth={2.4} />
        </span>
      </button>
      {effectiveRoute?.legs.some((leg) => leg.segmentCongestionGrade) && (
        <div className="map-congestion-legend" role="group" aria-label="구간 혼잡도 범례">
          {SEGMENT_CONGESTION_LEVELS.map((level) => (
            <span className="map-congestion-legend-item" key={level.grade}>
              <i aria-hidden="true" style={{ backgroundColor: level.color }} />
              {level.label}
            </span>
          ))}
        </div>
      )}
      {status !== 'ready' && (
        <div
          className={`map-state${showCongestionPreview ? ' congestion-preview-state' : ''}`}
          role="status"
        >
          <p>{status === 'loading' ? '지도를 불러오고 있어요' : '지도를 불러오지 못했어요'}</p>
          {status === 'error' && (
            <button className="secondary" onClick={retry}>
              <RotateCw size={15} />
              다시 시도
            </button>
          )}
        </div>
      )}
      <div className={`map-bottom-controls${showSelectedPlaceInfo ? ' has-place-info' : ''}`}>
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
        {showSelectedPlaceInfo && selectedPlace && !bikeStockStation && (
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
              {selectedPlace.address && <p>{selectedPlace.address}</p>}
              {selectedPlace.kind === '따릉이 대여소' &&
                (selectedPlace.dockCount !== undefined ||
                  selectedPlace.distanceMeters !== undefined) && (
                  <div className="map-place-info-meta">
                    {selectedPlace.dockCount !== undefined && (
                      <span>거치대 총 {selectedPlace.dockCount}개</span>
                    )}
                    {selectedPlace.distanceMeters !== undefined && (
                      <span>조회한 지도 중심에서 {Math.round(selectedPlace.distanceMeters)}m</span>
                    )}
                  </div>
                )}
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
      {bikeStockStation &&
        createPortal(
          <BikeStockSheet
            station={bikeStockStation}
            state={bikeStockState}
            stock={bikeStock}
            onClose={closeBikeStock}
            onRetry={() => selectBikeStation(bikeStockStation)}
          />,
          document.querySelector('.page-viewport') || document.body,
        )}
    </div>
  )
}
