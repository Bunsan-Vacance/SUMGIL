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
import {
  createRouteEndpointOverlay,
  createRouteSvgOverlay,
  getRouteEndpointCandidates,
  routeEndpointPlace,
  routeLineStyle,
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
) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<KakaoMapInstance | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  const ownMarker = useRef<MapOverlay | null>(null)
  const stationMarkers = useRef(new Map<string, BikeStationOverlay>())
  const stationClusterMarkers = useRef(new Map<string, BikeStationClusterOverlay>())
  const messageRef = useRef(onMessage)
  const placeRef = useRef(onPlaceSelect)
  const focusedRef = useRef(focusedPlace)
  const highlightedRef = useRef(highlightedPlace)
  const routeActiveRef = useRef(Boolean(route))
  const bikeStationsVisibleRef = useRef(bikeStationsVisible)
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

  useEffect(() => {
    stationMarkers.current.forEach((marker, id) =>
      marker.setSelected(
        focusedRef.current?.id === `bike-station:${id}` ||
          highlightedRef.current?.id === `bike-station:${id}`,
      ),
    )
  }, [focusedPlace, highlightedPlace])

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
    const homeTopbar = shell.querySelector<HTMLElement>('.home-topbar')
    const browseToolbar = shell.querySelector<HTMLElement>('.browse-toolbar')
    const guideTop = shell.querySelector<HTMLElement>('.guide-top')
    const bottomSheet = shell.querySelector<HTMLElement>('.bottom-sheet')
    const resize = () => {
      const topOffset =
        homePanel?.offsetHeight ||
        homeTopbar?.offsetHeight ||
        browseToolbar?.offsetHeight ||
        guideTop?.offsetHeight ||
        0
      const bottomOffset = bottomSheet?.offsetHeight || 0
      wrapper.style.top = `${topOffset}px`
      wrapper.style.height = `${Math.max(1, shell.clientHeight - topOffset - bottomOffset)}px`
    }
    const observer = new ResizeObserver(resize)
    observer.observe(shell)
    if (homePanel) observer.observe(homePanel)
    if (homeTopbar) observer.observe(homeTopbar)
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
            if (stationMarkers.current.has(station.id)) return
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
            })
            .catch(() => {
              if (cancelled || controller.signal.aborted || requestId !== nearbyRequestId) return
              stationListRef.current = []
              syncStationMarkers()
              messageRef.current('주변 대여소 정보를 불러오지 못했어요.')
            })
        }
        syncStationMarkers()
        idleHandler = () => {
          syncStationMarkers()
          loadNearbyStations()
        }
        maps.event.addListener(instance, 'idle', idleHandler)
        if (bikeStationRepository) loadNearbyStations()
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
          if (routeBoundsRef.current) {
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
      stationMarkers.current.forEach((marker) => marker.destroy())
      stationMarkers.current.clear()
      stationClusterMarkers.current.forEach((marker) => marker.destroy())
      stationClusterMarkers.current.clear()
      ownMarker.current?.setMap(null)
      ownMarker.current = null
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
      ? route.legs.flatMap((leg) =>
          (leg.geometry?.coordinates || []).map((coordinates) => ({
            coordinates,
            style: routeLineStyle(leg),
          })),
        )
      : (route.geometry?.coordinates || []).map((coordinates) => ({
          coordinates,
          style: { strokeColor: '#6379bd', strokeStyle: 'solid' },
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
    if (pointCount > 1) {
      routeBoundsRef.current = bounds
      instance.setBounds(bounds, 40, 35, 35, 35)
    } else if (pointCount === 1) {
      routeBoundsRef.current = bounds
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
    map.current.panTo(point)
  }
  return {
    container,
    status,
    retry: () => setAttempt((value) => value + 1),
    showPosition,
    locationScope: (origin?.id || 'browse') + '-' + destination?.id + '-' + attempt,
  }
}
