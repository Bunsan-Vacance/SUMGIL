import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Check, RotateCw } from 'lucide-react'
import { bikeStationRepository } from '../../api/repositories'
import {
  loadKakaoMaps,
  type KakaoMapClickEvent,
  type KakaoMapInstance,
  type MapOverlay,
} from '../../lib/kakao/sdk'
import type { Place } from '../route/types'
import {
  createBikeStationClusterOverlay,
  createBikeStationOverlay,
  groupVisibleBikeStations,
  type BikeStationOverlay,
  type BikeStationClusterOverlay,
  zoomToBikeStationCluster,
} from './bikeStationMarkers'
import {
  bikeStations,
  nearbyStationToBikeStation,
  stationToPlace,
  type BikeStation,
} from './bikeStations'

interface Props {
  target: 'origin' | 'destination'
  onCancel: () => void
  onSelect: (place: Place) => void
}

function coordinateLabel(lat: number, lng: number) {
  return `위도 ${lat.toFixed(6)}, 경도 ${lng.toFixed(6)}`
}

export default function MapPlacePicker({ target, onCancel, onSelect }: Props) {
  const canvas = useRef<HTMLDivElement>(null)
  const map = useRef<KakaoMapInstance | null>(null)
  const marker = useRef<MapOverlay | null>(null)
  const stationMarkers = useRef(new Map<string, BikeStationOverlay>())
  const stationClusterMarkers = useRef(new Map<string, BikeStationClusterOverlay>())
  const stationList = useRef(bikeStationRepository ? [] : bikeStations)
  const selectedStationId = useRef<string | null>(null)
  const requestId = useRef(0)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  const [geocoding, setGeocoding] = useState(false)
  const [message, setMessage] = useState('')
  const [selected, setSelected] = useState<Place | null>(null)

  useEffect(() => {
    let cancelled = false
    let maps: Awaited<ReturnType<typeof loadKakaoMaps>> | null = null
    let clickHandler: ((event: KakaoMapClickEvent) => void) | null = null
    let idleHandler: (() => void) | null = null
    let resizeObserver: ResizeObserver | null = null
    let nearbyAbort: AbortController | null = null
    let nearbyRequestId = 0
    const element = canvas.current
    if (!element) return

    setStatus('loading')
    loadKakaoMaps()
      .then((loaded) => {
        if (cancelled) return
        maps = loaded
        stationList.current = bikeStationRepository ? [] : bikeStations
        const instance = new loaded.Map(element, {
          center: new loaded.LatLng(37.50162, 127.03944),
          level: 5,
        })
        map.current = instance
        const geocoder = new loaded.services.Geocoder()
        const selectStation = (station: BikeStation) => {
          requestId.current++
          marker.current?.setMap(null)
          marker.current = null
          selectedStationId.current = station.id
          setSelected(stationToPlace(station))
          setMessage('')
          setGeocoding(false)
          stationMarkers.current.forEach((stationMarker, id) =>
            stationMarker.setSelected(id === station.id),
          )
        }
        const syncStationMarkers = () => {
          const groups = groupVisibleBikeStations(loaded, instance, stationList.current)
          const individualGroups = groups.filter((group) => group.stations.length === 1)
          const visibleIds = new Set(individualGroups.map((group) => group.stations[0].id))
          stationMarkers.current.forEach((stationMarker, id) => {
            if (!visibleIds.has(id)) {
              stationMarker.destroy()
              stationMarkers.current.delete(id)
            }
          })
          individualGroups.forEach((group) => {
            const station = group.stations[0]
            if (stationMarkers.current.has(station.id)) return
            stationMarkers.current.set(
              station.id,
              createBikeStationOverlay(
                loaded,
                instance,
                station,
                selectedStationId.current === station.id,
                () => selectStation(station),
              ),
            )
          })
          stationClusterMarkers.current.forEach((stationClusterMarker) =>
            stationClusterMarker.destroy(),
          )
          stationClusterMarkers.current.clear()
          groups
            .filter((group) => group.stations.length > 1)
            .forEach((group) => {
              const key = group.stations.map((station) => station.id).join('|')
              stationClusterMarkers.current.set(
                key,
                createBikeStationClusterOverlay(loaded, instance, group, () =>
                  zoomToBikeStationCluster(loaded, instance, group),
                ),
              )
            })
        }
        const loadNearbyStations = () => {
          if (!bikeStationRepository) return
          const center = instance.getCenter()
          nearbyAbort?.abort()
          const controller = new AbortController()
          nearbyAbort = controller
          const requestId = ++nearbyRequestId
          bikeStationRepository
            .nearby(
              {
                lat: center.getLat(),
                lng: center.getLng(),
                radiusMeters: 3000,
                limit: 100,
              },
              controller.signal,
            )
            .then((stations) => {
              if (cancelled || controller.signal.aborted || requestId !== nearbyRequestId) return
              stationList.current = stations.map(nearbyStationToBikeStation)
              syncStationMarkers()
            })
            .catch(() => {
              if (cancelled || controller.signal.aborted || requestId !== nearbyRequestId) return
              stationList.current = []
              syncStationMarkers()
              setMessage('주변 대여소 정보를 불러오지 못했어요.')
            })
        }
        syncStationMarkers()
        idleHandler = () => {
          syncStationMarkers()
          loadNearbyStations()
        }
        loaded.event.addListener(instance, 'idle', idleHandler)
        if (bikeStationRepository) loadNearbyStations()
        clickHandler = (event) => {
          const lat = event.latLng.getLat()
          const lng = event.latLng.getLng()
          const id = ++requestId.current
          if (
            !Number.isFinite(lat) ||
            !Number.isFinite(lng) ||
            lat < -90 ||
            lat > 90 ||
            lng < -180 ||
            lng > 180
          ) {
            setSelected(null)
            setGeocoding(false)
            setMessage('이 위치의 좌표를 확인하지 못했어요.')
            return
          }
          const fallback = coordinateLabel(lat, lng)
          const place: Place = {
            id: `map:${lat}:${lng}`,
            name: '지도에서 선택한 위치',
            address: fallback,
            kind: '지도 선택',
            lat,
            lng,
          }
          selectedStationId.current = null
          stationMarkers.current.forEach((stationMarker) => stationMarker.setSelected(false))
          marker.current?.setMap(null)
          marker.current = new loaded.Marker({
            map: instance,
            position: event.latLng,
            title: place.name,
          })
          setSelected(place)
          setMessage('')
          setGeocoding(true)
          try {
            geocoder.coord2Address(lng, lat, (results, resultStatus) => {
              if (cancelled || id !== requestId.current) return
              setGeocoding(false)
              const address =
                resultStatus === loaded.services.Status.OK
                  ? results[0]?.road_address?.address_name || results[0]?.address?.address_name
                  : undefined
              if (address?.trim()) {
                setSelected({ ...place, name: address.trim(), address: address.trim() })
                return
              }
              setMessage('이 위치의 주소를 찾지 못했어요. 좌표로 선택할 수 있어요.')
            })
          } catch {
            if (cancelled || id !== requestId.current) return
            setGeocoding(false)
            setMessage('주소를 확인하지 못했어요. 좌표로 선택할 수 있어요.')
          }
        }
        loaded.event.addListener(instance, 'click', clickHandler)
        resizeObserver = new ResizeObserver(() => {
          instance.relayout()
          syncStationMarkers()
          loadNearbyStations()
        })
        resizeObserver.observe(element)
        setStatus('ready')
      })
      .catch(() => {
        if (!cancelled) setStatus('error')
      })
    return () => {
      cancelled = true
      nearbyAbort?.abort()
      nearbyRequestId++
      requestId.current++
      if (maps && map.current) {
        if (clickHandler) maps.event.removeListener(map.current, 'click', clickHandler)
        if (idleHandler) maps.event.removeListener(map.current, 'idle', idleHandler)
      }
      resizeObserver?.disconnect()
      stationMarkers.current.forEach((stationMarker) => stationMarker.destroy())
      stationMarkers.current.clear()
      stationClusterMarkers.current.forEach((stationClusterMarker) =>
        stationClusterMarker.destroy(),
      )
      stationClusterMarkers.current.clear()
      selectedStationId.current = null
      marker.current?.setMap(null)
      marker.current = null
      map.current = null
      element.replaceChildren()
    }
  }, [attempt])

  return (
    <section className="map-picker">
      <header className="row map-picker-header">
        <button className="icon-button" aria-label="검색으로 돌아가기" onClick={onCancel}>
          <ArrowLeft />
        </button>
        <h2>{target === 'origin' ? '출발지' : '도착지'}를 지도에서 선택</h2>
      </header>
      <div className="map-picker-canvas">
        <div ref={canvas} className="kakao-map-canvas" aria-label="지도에서 장소 선택" />
        {status !== 'ready' && (
          <div className="map-state" role="status">
            <p>{status === 'loading' ? '지도를 불러오고 있어요' : '지도를 불러오지 못했어요'}</p>
            {status === 'error' && (
              <button className="secondary" onClick={() => setAttempt((value) => value + 1)}>
                <RotateCw size={15} />
                다시 시도
              </button>
            )}
          </div>
        )}
      </div>
      <div className="map-picker-footer">
        <p className="section-label">
          {selected
            ? geocoding
              ? '선택한 위치의 주소를 확인하고 있어요.'
              : selected.address || selected.name
            : '지도에서 위치를 눌러 주세요.'}
        </p>
        {selected?.kind === '따릉이 대여소' &&
          (selected.dockCount !== undefined || selected.distanceMeters !== undefined) && (
            <p className="map-picker-station-meta">
              {selected.dockCount !== undefined && `거치대 총 ${selected.dockCount}개`}
              {selected.dockCount !== undefined && selected.distanceMeters !== undefined && ' · '}
              {selected.distanceMeters !== undefined &&
                `조회한 지도 중심에서 ${Math.round(selected.distanceMeters)}m`}
            </p>
          )}
        {message && (
          <p className="error" role="alert">
            {message}
          </p>
        )}
        <div className="map-picker-actions">
          <button className="secondary" onClick={onCancel}>
            취소
          </button>
          <button
            className="primary"
            disabled={!selected}
            onClick={() => selected && onSelect(selected)}
          >
            <Check size={16} />
            {target === 'origin' ? '이 위치를 출발지로 설정' : '이 위치를 도착지로 설정'}
          </button>
        </div>
      </div>
    </section>
  )
}
