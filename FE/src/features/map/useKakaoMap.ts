import { useEffect, useRef, useState } from 'react'
import { bikeStationRepository } from '../../api/repositories'
import {
  loadKakaoMaps,
  type KakaoMapInstance,
  type KakaoMarker,
  type MapMarkerImage,
  type MapBounds,
  type MapOverlay,
  type MapPoint,
} from '../../lib/kakao/sdk'
import type { Place, Route } from '../route/types'
import {
  createBikeStationClusterOverlay,
  createBikeStationOverlay,
  groupVisibleBikeStations,
  type BikeStationOverlay,
  type BikeStationClusterOverlay,
  zoomToBikeStationCluster,
} from './bikeStationMarkers'
import { bikeStations, nearbyStationToBikeStation, stationToPlace } from './bikeStations'
import type { BikeStation } from './bikeStations'
import { createStationOverlay } from './stationMarkers'
import type { StationMarkerDatum, StationOverlay } from './stationMarkers'
import {
  createRouteEndpointOverlay,
  createRouteSvgOverlay,
  getRouteEndpointCandidates,
  routeEndpointPlace,
  routeLineStyle,
  ROUTE_LINE_COLOR,
  type RouteLineEntry,
  type RouteSvgOverlay,
  type RouteEndpointCandidate,
  type RouteEndpointOverlay,
} from './routeMapMarkers'

const NORMAL_MARKER_SRC = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="36" viewBox="0 0 28 36"><path fill="#6379bd" d="M14 0C6.3 0 0 6.1 0 13.6 0 23.6 14 36 14 36s14-12.4 14-22.4C28 6.1 21.7 0 14 0Z"/><circle cx="14" cy="13" r="5" fill="#fff"/></svg>',
)}`
const SELECTED_MARKER_SRC = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="46" viewBox="0 0 36 46"><path fill="#a92a70" d="M18 0C8.1 0 0 7.8 0 17.3 0 30.1 18 46 18 46s18-15.9 18-28.7C36 7.8 27.9 0 18 0Z"/><circle cx="18" cy="16" r="6" fill="#fff"/></svg>',
)}`
export type LivePosition = { latitude: number; longitude: number; accuracy: number } | null

function isValidLivePosition(position: LivePosition): position is NonNullable<LivePosition> {
  return Boolean(
    position &&
    Number.isFinite(position.latitude) &&
    position.latitude >= -90 &&
    position.latitude <= 90 &&
    Number.isFinite(position.longitude) &&
    position.longitude >= -180 &&
    position.longitude <= 180 &&
    Number.isFinite(position.accuracy) &&
    position.accuracy >= 0,
  )
}
export function useKakaoMap(
  origin: Place | null,
  destination: Place | null,
  onMessage: (message: string) => void,
  onPlaceSelect?: (place: Place) => void,
  places: Place[] = [],
  focusedPlace?: Place | null,
  highlightedPlace?: Place | null,
  route?: Route | null,
  bikeStationsVisible = true,
  livePosition: LivePosition = null,
  bikeStockBadges = false,
  stationDatums: StationMarkerDatum[] = [],
  selectedStationId: string | null = null,
  onStationSelect?: (datum: StationMarkerDatum) => void,
  onViewportChange?: (center: { lat: number; lng: number }) => void,
  onBikeStationsChange?: (stations: BikeStation[]) => void,
) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<KakaoMapInstance | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  const ownMarker = useRef<KakaoMarker | null>(null)
  const ownMarkerIsLive = useRef(false)
  const livePositionRef = useRef<LivePosition>(livePosition)
  const followLivePosition = useRef(false)
  const stationMarkers = useRef(new Map<string, BikeStationOverlay>())
  const stationClusterMarkers = useRef(new Map<string, BikeStationClusterOverlay>())
  const messageRef = useRef(onMessage)
  const placeRef = useRef(onPlaceSelect)
  const focusedRef = useRef(focusedPlace)
  const highlightedRef = useRef(highlightedPlace)
  const routeActiveRef = useRef(Boolean(route))
  const bikeStationsVisibleRef = useRef(bikeStationsVisible)
  const bikeStockBadgesRef = useRef(bikeStockBadges)
  const stationOverlays = useRef(new Map<string, StationOverlay>())
  const stationPositions = useRef(new Map<string, { lat: number; lng: number }>())
  const selectedStationIdRef = useRef(selectedStationId)
  const onStationSelectRef = useRef(onStationSelect)
  const onViewportChangeRef = useRef(onViewportChange)
  const onBikeStationsChangeRef = useRef(onBikeStationsChange)
  const markersRef = useRef(new Map<string, KakaoMarker>())
  const selectedMarkerRef = useRef<KakaoMarker | null>(null)
  const normalMarkerImageRef = useRef<MapMarkerImage | null>(null)
  const selectedMarkerImageRef = useRef<MapMarkerImage | null>(null)
  const stationListRef = useRef(bikeStationRepository ? [] : bikeStations)
  const routeLinesRef = useRef<RouteSvgOverlay | null>(null)
  const routeEndpointOverlaysRef = useRef<RouteEndpointOverlay[]>([])
  const routeBikeStationOverlaysRef = useRef<BikeStationOverlay[]>([])
  const routeBikeEndpointsRef = useRef<RouteEndpointCandidate[]>([])
  const syncStationMarkersRef = useRef<(() => void) | null>(null)
  const routeBoundsRef = useRef<MapBounds | null>(null)
  const mapsRef = useRef<Awaited<ReturnType<typeof loadKakaoMaps>> | null>(null)
  messageRef.current = onMessage
  placeRef.current = onPlaceSelect
  focusedRef.current = focusedPlace
  highlightedRef.current = highlightedPlace
  routeActiveRef.current = Boolean(route)
  bikeStationsVisibleRef.current = bikeStationsVisible
  bikeStockBadgesRef.current = bikeStockBadges
  selectedStationIdRef.current = selectedStationId
  onStationSelectRef.current = onStationSelect
  onViewportChangeRef.current = onViewportChange
  onBikeStationsChangeRef.current = onBikeStationsChange
  livePositionRef.current = livePosition

  useEffect(() => {
    stationMarkers.current.forEach((marker, id) =>
      marker.setSelected(
        focusedRef.current?.id === `bike-station:${id}` ||
          highlightedRef.current?.id === `bike-station:${id}`,
      ),
    )
  }, [focusedPlace, highlightedPlace])

  useEffect(() => {
    syncStationMarkersRef.current?.()
  }, [bikeStationsVisible, bikeStockBadges])

  useEffect(() => {
    const maps = mapsRef.current
    const instance = map.current
    if (status !== 'ready' || !maps || !instance) return
    const wanted = new Map(stationDatums.map((datum) => [datum.stationId, datum]))
    stationOverlays.current.forEach((overlay, id) => {
      if (!wanted.has(id)) {
        overlay.destroy()
        stationOverlays.current.delete(id)
      }
    })
    wanted.forEach((datum, id) => {
      const existing = stationOverlays.current.get(id)
      const previous = stationPositions.current.get(id)
      if (existing && previous && previous.lat === datum.lat && previous.lng === datum.lng) {
        existing.setGrade(datum.grade)
        return
      }
      existing?.destroy()
      stationPositions.current.set(id, { lat: datum.lat, lng: datum.lng })
      stationOverlays.current.set(
        id,
        createStationOverlay(maps, instance, datum, selectedStationIdRef.current === id, () =>
          onStationSelectRef.current?.(datum),
        ),
      )
    })
  }, [stationDatums, status])

  useEffect(() => {
    stationOverlays.current.forEach((overlay, id) => overlay.setSelected(id === selectedStationId))
  }, [selectedStationId])

  useEffect(() => {
    const active = Boolean(route)
    stationMarkers.current.forEach((marker) => marker.setRouteActive(active))
    stationClusterMarkers.current.forEach((marker) => marker.setRouteActive(active))
  }, [route])

  const updateMarkerSelection = () => {
    const selected = highlightedRef.current
      ? markersRef.current.get(highlightedRef.current.id) || null
      : null
    if (selectedMarkerRef.current && selectedMarkerRef.current !== selected) {
      const normalMarkerImage = normalMarkerImageRef.current
      if (normalMarkerImage) selectedMarkerRef.current.setImage(normalMarkerImage)
      selectedMarkerRef.current.setZIndex(1)
    }
    const selectedMarkerImage = selectedMarkerImageRef.current
    if (selected && selectedMarkerImage) {
      selected.setImage(selectedMarkerImage)
      selected.setZIndex(3)
    }
    selectedMarkerRef.current = selected
  }

  useEffect(() => {
    const wrapper = container.current!.parentElement!
    const shell = wrapper.parentElement!
    const homePanel = shell.querySelector<HTMLElement>('.home-panel')
    // 홈 상단 바(.home-topbar)는 지도 위에 겹치는 absolute 오버레이라 지도 높이에서 빼지 않는다.
    const browseToolbar = shell.querySelector<HTMLElement>('.browse-toolbar')
    const guideTop = shell.querySelector<HTMLElement>('.guide-top')
    const bottomSheet = shell.querySelector<HTMLElement>('.bottom-sheet')
    const resize = () => {
      const topOffset =
        homePanel?.offsetHeight || browseToolbar?.offsetHeight || guideTop?.offsetHeight || 0
      const bottomOffset = bottomSheet?.offsetHeight || 0
      wrapper.style.top = `${topOffset}px`
      wrapper.style.height = `${Math.max(1, shell.clientHeight - topOffset - bottomOffset)}px`
    }
    const observer = new ResizeObserver(resize)
    observer.observe(shell)
    if (homePanel) observer.observe(homePanel)
    if (browseToolbar) observer.observe(browseToolbar)
    if (guideTop) observer.observe(guideTop)
    if (bottomSheet) observer.observe(bottomSheet)
    resize()
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let cancelled = false
    let loadedMaps: Awaited<ReturnType<typeof loadKakaoMaps>> | null = null
    let observer: ResizeObserver | null = null
    let idleHandler: (() => void) | null = null
    let dragHandler: (() => void) | null = null
    let nearbyAbort: AbortController | null = null
    let nearbyRequestId = 0
    const markers: MapOverlay[] = []
    const markerListeners: Array<{ marker: MapOverlay; handler: () => void }> = []
    const canvas = container.current!
    stationListRef.current = bikeStationRepository ? [] : bikeStations
    setStatus('loading')
    loadKakaoMaps()
      .then((maps) => {
        if (cancelled) return
        loadedMaps = maps
        mapsRef.current = maps
        const instance = new maps.Map(canvas, {
          center: new maps.LatLng(37.50162, 127.03944),
          level: 5,
        })
        map.current = instance
        dragHandler = () => {
          followLivePosition.current = false
        }
        maps.event.addListener(instance, 'dragstart', dragHandler)
        const syncStationMarkers = () => {
          if (!bikeStationsVisibleRef.current) {
            stationMarkers.current.forEach((marker) => marker.destroy())
            stationMarkers.current.clear()
            stationClusterMarkers.current.forEach((marker) => marker.destroy())
            stationClusterMarkers.current.clear()
            return
          }
          const routeBikeIds = new Set(
            routeBikeEndpointsRef.current
              .map((candidate) => candidate.endpoint.id?.trim())
              .filter((id): id is string => Boolean(id)),
          )
          const groups = groupVisibleBikeStations(
            maps,
            instance,
            stationListRef.current.filter((station) => !routeBikeIds.has(station.id)),
          )
          const individualGroups = groups.filter((group) => group.stations.length === 1)
          const visibleIds = new Set(individualGroups.map((group) => group.stations[0].id))
          stationMarkers.current.forEach((marker, id) => {
            if (!visibleIds.has(id)) {
              marker.destroy()
              stationMarkers.current.delete(id)
            }
          })
          individualGroups.forEach((group) => {
            const station = group.stations[0]
            const existing = stationMarkers.current.get(station.id)
            if (existing) {
              if (bikeStockBadgesRef.current) existing.setBadge(station.availableBikes)
              return
            }
            stationMarkers.current.set(
              station.id,
              createBikeStationOverlay(
                maps,
                instance,
                station,
                focusedRef.current?.id === `bike-station:${station.id}` ||
                  highlightedRef.current?.id === `bike-station:${station.id}`,
                () => {
                  placeRef.current?.(stationToPlace(station))
                },
                routeActiveRef.current,
                1,
                bikeStockBadgesRef.current ? { count: station.availableBikes } : undefined,
              ),
            )
          })
          stationClusterMarkers.current.forEach((marker) => marker.destroy())
          stationClusterMarkers.current.clear()
          groups
            .filter((group) => group.stations.length > 1)
            .forEach((group) => {
              const key = group.stations.map((station) => station.id).join('|')
              stationClusterMarkers.current.set(
                key,
                createBikeStationClusterOverlay(
                  maps,
                  instance,
                  group,
                  () => zoomToBikeStationCluster(maps, instance, group),
                  routeActiveRef.current,
                ),
              )
            })
        }
        syncStationMarkersRef.current = syncStationMarkers
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
              stationListRef.current = stations.map(nearbyStationToBikeStation)
              syncStationMarkers()
              onBikeStationsChangeRef.current?.(stationListRef.current)
            })
            .catch(() => {
              if (cancelled || controller.signal.aborted || requestId !== nearbyRequestId) return
              stationListRef.current = []
              syncStationMarkers()
              onBikeStationsChangeRef.current?.(stationListRef.current)
              messageRef.current('주변 대여소 정보를 불러오지 못했어요.')
            })
        }
        syncStationMarkers()
        const notifyViewport = () => {
          const center = instance.getCenter()
          onViewportChangeRef.current?.({ lat: center.getLat(), lng: center.getLng() })
        }
        idleHandler = () => {
          syncStationMarkers()
          loadNearbyStations()
          notifyViewport()
        }
        maps.event.addListener(instance, 'idle', idleHandler)
        if (bikeStationRepository) loadNearbyStations()
        // 목업 모드는 정적 대여소 목록을 지도 준비 시 한 번만 알린다.
        else onBikeStationsChangeRef.current?.(stationListRef.current)
        const bounds = new maps.LatLngBounds()
        normalMarkerImageRef.current = new maps.MarkerImage(
          NORMAL_MARKER_SRC,
          new maps.Size(28, 36),
          {
            offset: new maps.Point(14, 36),
          },
        )
        selectedMarkerImageRef.current = new maps.MarkerImage(
          SELECTED_MARKER_SRC,
          new maps.Size(36, 46),
          {
            offset: new maps.Point(18, 46),
          },
        )
        const search = new maps.services.Places()
        const targets = places
        let resolved = 0
        const addMarker = (place: Place, point: MapPoint) => {
          if (place.kind !== '따릉이 대여소') {
            const marker = new maps.Marker({
              map: instance,
              position: point,
              title: place.name,
              clickable: true,
            })
            marker.setImage(normalMarkerImageRef.current!)
            marker.setZIndex(1)
            markers.push(marker)
            markersRef.current.set(place.id, marker)
            const markerClick = () => {
              if (!cancelled) placeRef.current?.(place)
            }
            maps.event.addListener(marker, 'click', markerClick)
            markerListeners.push({ marker, handler: markerClick })
          }
          bounds.extend(point)
          resolved++
          if (targets.length === 1) instance.setCenter(point)
          else if (resolved === targets.length) instance.setBounds(bounds, 40, 35, 35, 35)
          updateMarkerSelection()
        }
        targets.forEach((place) => {
          if (place.lat !== undefined && place.lng !== undefined) {
            addMarker(place, new maps.LatLng(place.lat, place.lng))
            return
          }
          search.keywordSearch(`서울 ${place.name}`, (results, status) => {
            if (cancelled) return
            if (status !== maps.services.Status.OK || !results[0]) {
              messageRef.current(`${place.name} 위치를 찾지 못했어요.`)
              return
            }
            const point = new maps.LatLng(Number(results[0].y), Number(results[0].x))
            addMarker(place, point)
          })
        })
        observer = new ResizeObserver(() => {
          const center = instance.getCenter()
          instance.relayout()
          const livePosition = livePositionRef.current
          if (isValidLivePosition(livePosition)) {
            if (followLivePosition.current) {
              instance.panTo(new maps.LatLng(livePosition.latitude, livePosition.longitude))
            } else {
              instance.setCenter(center)
            }
          } else if (routeBoundsRef.current) {
            instance.setBounds(routeBoundsRef.current, 40, 35, 35, 35)
          } else {
            const focused = focusedRef.current
            if (
              focused?.lat !== undefined &&
              focused.lng !== undefined &&
              Number.isFinite(focused.lat) &&
              Number.isFinite(focused.lng)
            ) {
              instance.panTo(new maps.LatLng(focused.lat, focused.lng))
            } else {
              instance.setCenter(center)
            }
          }
          syncStationMarkers()
          loadNearbyStations()
        })
        observer.observe(canvas)
        notifyViewport()
        setStatus('ready')
      })
      .catch(() => {
        if (!cancelled) setStatus('error')
      })
    return () => {
      cancelled = true
      nearbyAbort?.abort()
      nearbyRequestId++
      observer?.disconnect()
      if (loadedMaps) {
        markerListeners.forEach(({ marker, handler }) =>
          loadedMaps!.event.removeListener(marker, 'click', handler),
        )
      }
      markers.forEach((marker) => marker.setMap(null))
      markersRef.current.clear()
      selectedMarkerRef.current = null
      normalMarkerImageRef.current = null
      selectedMarkerImageRef.current = null
      mapsRef.current = null
      if (idleHandler && map.current && loadedMaps)
        loadedMaps.event.removeListener(map.current, 'idle', idleHandler)
      if (dragHandler && map.current && loadedMaps)
        loadedMaps.event.removeListener(map.current, 'dragstart', dragHandler)
      stationMarkers.current.forEach((marker) => marker.destroy())
      stationMarkers.current.clear()
      stationClusterMarkers.current.forEach((marker) => marker.destroy())
      stationClusterMarkers.current.clear()
      stationOverlays.current.forEach((overlay) => overlay.destroy())
      stationOverlays.current.clear()
      stationPositions.current.clear()
      ownMarker.current?.setMap(null)
      ownMarker.current = null
      ownMarkerIsLive.current = false
      followLivePosition.current = false
      map.current = null
      routeLinesRef.current?.destroy()
      routeLinesRef.current = null
      routeEndpointOverlaysRef.current.forEach((overlay) => overlay.destroy())
      routeEndpointOverlaysRef.current = []
      routeBikeStationOverlaysRef.current.forEach((overlay) => overlay.destroy())
      routeBikeStationOverlaysRef.current = []
      routeBikeEndpointsRef.current = []
      syncStationMarkersRef.current = null
      routeBoundsRef.current = null
      canvas.replaceChildren()
    }
  }, [origin, destination, places, attempt])

  useEffect(() => {
    routeLinesRef.current?.destroy()
    routeLinesRef.current = null
    routeEndpointOverlaysRef.current.forEach((overlay) => overlay.destroy())
    routeEndpointOverlaysRef.current = []
    routeBikeStationOverlaysRef.current.forEach((overlay) => overlay.destroy())
    routeBikeStationOverlaysRef.current = []
    routeBikeEndpointsRef.current = []
    syncStationMarkersRef.current?.()
    routeBoundsRef.current = null
    const maps = mapsRef.current
    const instance = map.current
    if (!maps || !instance || status !== 'ready' || !route) return
    const bounds = new maps.LatLngBounds()
    let pointCount = 0
    const endpointCandidates = getRouteEndpointCandidates(route)
    const bikeCandidates = endpointCandidates.filter((candidate) => candidate.bikeRoles?.length)
    routeBikeEndpointsRef.current = bikeCandidates
    syncStationMarkersRef.current?.()
    endpointCandidates.forEach(({ endpoint }) => {
      bounds.extend(new maps.LatLng(endpoint.lat, endpoint.lng))
      pointCount += 1
    })
    const hasLegGeometry = route.legs.some((leg) => leg.geometry?.coordinates.length)
    const lineEntries: RouteLineEntry[] = hasLegGeometry
      ? route.legs.flatMap((leg) => {
          const coordinates = leg.geometry?.coordinates || []
          const lineParts =
            leg.mode === 'walk' || leg.mode === 'bike' ? [coordinates.flat()] : coordinates
          return lineParts
            .filter((part) => part.length)
            .map((part) => ({ coordinates: part, style: routeLineStyle(leg) }))
        })
      : (route.geometry?.coordinates || []).map((coordinates) => ({
          coordinates,
          style: { strokeColor: ROUTE_LINE_COLOR, strokeStyle: 'solid' },
        }))
    let validLineCount = 0
    lineEntries.forEach(({ coordinates }) => {
      const path = coordinates
        .filter(
          ([lng, lat]) =>
            Number.isFinite(lng) &&
            Number.isFinite(lat) &&
            lng >= -180 &&
            lng <= 180 &&
            lat >= -90 &&
            lat <= 90,
        )
        .map(([lng, lat]) => new maps.LatLng(lat, lng))
      if (path.length < 2) return
      path.forEach((point) => bounds.extend(point))
      pointCount += path.length
      validLineCount += 1
    })
    if (pointCount > 1) {
      routeBoundsRef.current = bounds
      if (!followLivePosition.current) instance.setBounds(bounds, 40, 35, 35, 35)
    } else if (pointCount === 1) {
      routeBoundsRef.current = bounds
    }
    if (validLineCount) routeLinesRef.current = createRouteSvgOverlay(maps, instance, lineEntries)
    routeBikeStationOverlaysRef.current = bikeStationsVisible
      ? bikeCandidates.map((candidate) =>
          createBikeStationOverlay(
            maps,
            instance,
            {
              id: `route-bike-endpoint:${candidate.endpoint.id || `${candidate.endpoint.lat}:${candidate.endpoint.lng}`}`,
              name: candidate.endpoint.name?.trim() || '따릉이 대여소',
              address: candidate.bikeRoles!.map((role) => `따릉이 ${role}`).join(' · '),
              lat: candidate.endpoint.lat,
              lng: candidate.endpoint.lng,
              ...(candidate.endpoint.rentalId ? { rentalId: candidate.endpoint.rentalId } : {}),
            },
            false,
            () => placeRef.current?.(routeEndpointPlace(candidate)),
            false,
            10,
          ),
        )
      : []
    routeEndpointOverlaysRef.current = endpointCandidates
      .filter((candidate) => !candidate.bikeRoles?.length)
      .map((candidate) =>
        createRouteEndpointOverlay(maps, instance, candidate, (place) => placeRef.current?.(place)),
      )
    const livePosition = livePositionRef.current
    if (followLivePosition.current && isValidLivePosition(livePosition)) {
      instance.panTo(new maps.LatLng(livePosition.latitude, livePosition.longitude))
    }
    return () => {
      routeLinesRef.current?.destroy()
      routeLinesRef.current = null
      routeEndpointOverlaysRef.current.forEach((overlay) => overlay.destroy())
      routeEndpointOverlaysRef.current = []
      routeBikeStationOverlaysRef.current.forEach((overlay) => overlay.destroy())
      routeBikeStationOverlaysRef.current = []
      routeBikeEndpointsRef.current = []
      syncStationMarkersRef.current?.()
      routeBoundsRef.current = null
    }
  }, [bikeStationsVisible, route, status])

  useEffect(() => {
    if (!isValidLivePosition(livePosition)) {
      if (ownMarkerIsLive.current) {
        ownMarker.current?.setMap(null)
        ownMarker.current = null
        ownMarkerIsLive.current = false
      }
      followLivePosition.current = false
      return
    }
    const maps = mapsRef.current
    const instance = map.current
    if (!maps || !instance || status !== 'ready') return
    const point = new maps.LatLng(livePosition.latitude, livePosition.longitude)
    if (!ownMarker.current || !ownMarkerIsLive.current) {
      ownMarker.current?.setMap(null)
      ownMarker.current = new maps.Marker({ map: instance, position: point, title: '현재 위치' })
      followLivePosition.current = true
    } else {
      ownMarker.current.setPosition(point)
    }
    ownMarkerIsLive.current = true
    if (followLivePosition.current) instance.panTo(point)
  }, [livePosition, status])

  useEffect(() => {
    updateMarkerSelection()
    if (!focusedPlace || !map.current || status !== 'ready') return
    const maps = mapsRef.current
    if (
      !maps ||
      focusedPlace.lat === undefined ||
      focusedPlace.lng === undefined ||
      !Number.isFinite(focusedPlace.lat) ||
      !Number.isFinite(focusedPlace.lng)
    )
      return
    map.current.setLevel(3)
    map.current.panTo(new maps.LatLng(focusedPlace.lat, focusedPlace.lng))
  }, [focusedPlace, highlightedPlace, status])

  const showPosition = (position: GeolocationPosition) => {
    const maps = window.kakao?.maps
    if (!map.current || !maps) return
    const point = new maps.LatLng(position.coords.latitude, position.coords.longitude)
    ownMarker.current?.setMap(null)
    ownMarker.current = new maps.Marker({ map: map.current, position: point, title: '현재 위치' })
    ownMarkerIsLive.current = false
    followLivePosition.current = false
    map.current.panTo(point)
  }
  const resumeLivePosition = () => {
    const position = livePositionRef.current
    const maps = mapsRef.current
    if (!isValidLivePosition(position) || !maps || !map.current) return false
    const point = new maps.LatLng(position.latitude, position.longitude)
    if (!ownMarker.current || !ownMarkerIsLive.current) {
      ownMarker.current?.setMap(null)
      ownMarker.current = new maps.Marker({ map: map.current, position: point, title: '현재 위치' })
      ownMarkerIsLive.current = true
    } else {
      ownMarker.current.setPosition(point)
    }
    followLivePosition.current = true
    map.current.panTo(point)
    return true
  }
  return {
    container,
    status,
    retry: () => setAttempt((value) => value + 1),
    showPosition,
    resumeLivePosition,
    locationScope: (origin?.id || 'browse') + '-' + destination?.id + '-' + attempt,
  }
}
