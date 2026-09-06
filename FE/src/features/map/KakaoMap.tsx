import { LocateFixed, RotateCw } from 'lucide-react'
import type { Place } from '../route/types'
import { useKakaoMap } from './useKakaoMap'
import { useCurrentLocation } from './useCurrentLocation'
export default function KakaoMap({
  origin,
  destination,
  onMessage,
}: {
  origin: Place
  destination: Place | null
  onMessage: (message: string) => void
}) {
  const { container, status, retry, showPosition, locationScope } = useKakaoMap(
    origin,
    destination,
    onMessage,
  )
  const { locating, locate } = useCurrentLocation(showPosition, onMessage, locationScope)
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
    </div>
  )
}
