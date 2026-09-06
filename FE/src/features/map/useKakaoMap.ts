import { useEffect, useRef, useState } from 'react'
import { loadKakaoMaps, type KakaoMapInstance, type MapOverlay } from '../../lib/kakao/sdk'
import type { Place } from '../route/types'
export function useKakaoMap(
  origin: Place,
  destination: Place | null,
  onMessage: (message: string) => void,
) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<KakaoMapInstance | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  const ownMarker = useRef<MapOverlay | null>(null)
  const messageRef = useRef(onMessage)
  messageRef.current = onMessage

  useEffect(() => {
    const wrapper = container.current!.parentElement!
    const shell = wrapper.parentElement!
    const sheet = shell.querySelector<HTMLElement>('.bottom-sheet, .home-panel')
    const resize = () => {
      wrapper.style.height = `${Math.max(1, shell.clientHeight - (sheet?.offsetHeight || 0))}px`
    }
    const observer = new ResizeObserver(resize)
    observer.observe(shell)
    if (sheet) observer.observe(sheet)
    resize()
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let cancelled = false
    let observer: ResizeObserver | null = null
    const markers: MapOverlay[] = []
    const canvas = container.current!
    setStatus('loading')
    loadKakaoMaps()
      .then((maps) => {
        if (cancelled) return
        const instance = new maps.Map(canvas, {
          center: new maps.LatLng(37.50162, 127.03944),
          level: 5,
        })
        map.current = instance
        const bounds = new maps.LatLngBounds()
        const search = new maps.services.Places()
        const targets = destination ? [origin, destination] : [origin]
        let resolved = 0
        targets.forEach((place) => {
          search.keywordSearch(`서울 ${place.name}`, (results, status) => {
            if (cancelled) return
            if (status !== maps.services.Status.OK || !results[0]) {
              messageRef.current(`${place.name} 위치를 찾지 못했어요.`)
              return
            }
            const point = new maps.LatLng(Number(results[0].y), Number(results[0].x))
            markers.push(new maps.Marker({ map: instance, position: point, title: place.name }))
            bounds.extend(point)
            resolved++
            if (targets.length === 1) instance.setCenter(point)
            else if (resolved === targets.length) instance.setBounds(bounds, 40, 35, 35, 35)
          })
        })
        observer = new ResizeObserver(() => {
          const center = instance.getCenter()
          instance.relayout()
          instance.setCenter(center)
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
      markers.forEach((marker) => marker.setMap(null))
      ownMarker.current?.setMap(null)
      ownMarker.current = null
      map.current = null
      canvas.replaceChildren()
    }
  }, [origin, destination, attempt])

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
    locationScope: origin.id + '-' + destination?.id + '-' + attempt,
  }
}
