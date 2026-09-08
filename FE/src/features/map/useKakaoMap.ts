import { useEffect, useRef, useState } from 'react'
import {
  loadKakaoMaps,
  type KakaoMapInstance,
  type KakaoMarker,
  type MapMarkerImage,
  type MapOverlay,
  type MapPoint,
} from '../../lib/kakao/sdk'
import type { Place } from '../route/types'

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
) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<KakaoMapInstance | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  const ownMarker = useRef<MapOverlay | null>(null)
  const messageRef = useRef(onMessage)
  const placeRef = useRef(onPlaceSelect)
  const focusedRef = useRef(focusedPlace)
  const highlightedRef = useRef(highlightedPlace)
  const markersRef = useRef(new Map<string, KakaoMarker>())
  const selectedMarkerRef = useRef<KakaoMarker | null>(null)
  const normalMarkerImageRef = useRef<MapMarkerImage | null>(null)
  const selectedMarkerImageRef = useRef<MapMarkerImage | null>(null)
  messageRef.current = onMessage
  placeRef.current = onPlaceSelect
  focusedRef.current = focusedPlace
  highlightedRef.current = highlightedPlace

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
    const browseToolbar = shell.querySelector<HTMLElement>('.browse-toolbar')
    const bottomSheet = shell.querySelector<HTMLElement>('.bottom-sheet')
    const resize = () => {
      const topOffset = homePanel?.offsetHeight || browseToolbar?.offsetHeight || 0
      const bottomOffset = bottomSheet?.offsetHeight || 0
      wrapper.style.top = `${topOffset}px`
      wrapper.style.height = `${Math.max(1, shell.clientHeight - topOffset - bottomOffset)}px`
    }
    const observer = new ResizeObserver(resize)
    observer.observe(shell)
    if (homePanel) observer.observe(homePanel)
    if (browseToolbar) observer.observe(browseToolbar)
    if (bottomSheet) observer.observe(bottomSheet)
    resize()
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let cancelled = false
    let loadedMaps: Awaited<ReturnType<typeof loadKakaoMaps>> | null = null
    let observer: ResizeObserver | null = null
    const markers: MapOverlay[] = []
    const markerListeners: Array<{ marker: MapOverlay; handler: () => void }> = []
    const canvas = container.current!
    setStatus('loading')
    loadKakaoMaps()
      .then((maps) => {
        if (cancelled) return
        loadedMaps = maps
        const instance = new maps.Map(canvas, {
          center: new maps.LatLng(37.50162, 127.03944),
          level: 5,
        })
        map.current = instance
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
        })
        observer.observe(canvas)
        setStatus('ready')
      })
      .catch(() => {
        if (!cancelled) setStatus('error')
      })
    return () => {
      cancelled = true
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
      ownMarker.current?.setMap(null)
      ownMarker.current = null
      map.current = null
      canvas.replaceChildren()
    }
  }, [origin, destination, places, attempt])

  useEffect(() => {
    updateMarkerSelection()
    if (!focusedPlace || !map.current || status !== 'ready') return
    const maps = window.kakao?.maps
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
