import { useEffect, useRef, useState, type RefObject } from 'react'
import { loadKakaoMaps, type KakaoMapInstance, type KakaoMaps } from '../../lib/kakao/sdk'
import type { LatLng } from './types'

// 운영자 뷰 전용 경량 지도 훅. 경로 탐색용 useKakaoMap과 분리해 바텀시트·경로 흐름과 결합하지 않는다.

export interface OpsBounds {
  sw: LatLng
  ne: LatLng
}

export const OPS_MAP_CENTER: LatLng = { lat: 37.5665, lng: 126.978 }
export const OPS_MAP_LEVEL = 5
export const OPS_BOUNDS_DEBOUNCE_MS = 300

interface CornerPoint {
  getLat(): number
  getLng(): number
}
// SDK 타입(MapBounds)에는 모서리 접근자가 없어 이 파일에서만 좁은 형태로 확인한다.
interface CornerBounds {
  getSouthWest(): CornerPoint
  getNorthEast(): CornerPoint
}

function hasCorners(value: unknown): value is CornerBounds {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as CornerBounds).getSouthWest === 'function' &&
    typeof (value as CornerBounds).getNorthEast === 'function'
  )
}

export function readMapBounds(map: KakaoMapInstance): OpsBounds | null {
  const bounds: unknown = map.getBounds()
  if (!hasCorners(bounds)) return null
  const sw = bounds.getSouthWest()
  const ne = bounds.getNorthEast()
  const result = {
    sw: { lat: sw.getLat(), lng: sw.getLng() },
    ne: { lat: ne.getLat(), lng: ne.getLng() },
  }
  const finite = [result.sw.lat, result.sw.lng, result.ne.lat, result.ne.lng].every(Number.isFinite)
  return finite ? result : null
}

export interface OpsMapHandle {
  maps: KakaoMaps
  map: KakaoMapInstance
}

export function useOpsMap(
  containerRef: RefObject<HTMLElement | null>,
  onBoundsChange: (bounds: OpsBounds) => void,
) {
  const [handle, setHandle] = useState<OpsMapHandle | null>(null)
  const [mapError, setMapError] = useState<string | null>(null)
  const callback = useRef(onBoundsChange)
  useEffect(() => {
    callback.current = onBoundsChange
  }, [onBoundsChange])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let cleanup: (() => void) | undefined
    loadKakaoMaps().then(
      (maps) => {
        if (cancelled) return
        const map = new maps.Map(container, {
          center: new maps.LatLng(OPS_MAP_CENTER.lat, OPS_MAP_CENTER.lng),
          level: OPS_MAP_LEVEL,
        })
        const report = () => {
          clearTimeout(timer)
          timer = setTimeout(() => {
            const bounds = readMapBounds(map)
            if (bounds) callback.current(bounds)
          }, OPS_BOUNDS_DEBOUNCE_MS)
        }
        maps.event.addListener(map, 'idle', report)
        cleanup = () => maps.event.removeListener(map, 'idle', report)
        setHandle({ maps, map })
        report()
      },
      (error: unknown) => {
        if (cancelled) return
        setMapError(
          error instanceof Error && error.message === 'missing-key'
            ? '지도 키(VITE_KAKAO_MAP_APP_KEY)가 설정되지 않아 지도를 표시할 수 없어요.'
            : '지도를 불러오지 못했어요.',
        )
      },
    )
    return () => {
      cancelled = true
      clearTimeout(timer)
      cleanup?.()
      setHandle(null)
    }
  }, [containerRef])

  return { handle, mapError }
}
