import { useEffect, useState } from 'react'
import type { Place } from '../route/types'
import type { HomeLayer } from './homeLayers'

/**
 * 홈 지도의 레이어 선택과 선택한 대여소를 소유한다(App에서 한 번 호출).
 * 레이어는 화면을 오가도 유지하고, 선택한 대여소는 홈을 벗어나면(active=false) 해제한다.
 */
export function useHomeMapLayers(active = true, initialLayer: HomeLayer | null = 'bike') {
  const [layer, setLayerState] = useState<HomeLayer | null>(initialLayer)
  const [selectedStation, setSelectedStation] = useState<Place | null>(null)
  useEffect(() => {
    if (!active) setSelectedStation(null)
  }, [active])
  const setLayer = (next: HomeLayer | null) => {
    setLayerState(next)
    // 따릉이 레이어를 끄면 선택한 대여소도 함께 해제한다.
    if (next !== 'bike') setSelectedStation(null)
  }
  const selectStation = (place: Place) => {
    if (active && place.kind === '따릉이 대여소') setSelectedStation(place)
  }
  const clearStation = () => setSelectedStation(null)
  return { layer, setLayer, selectedStation, selectStation, clearStation }
}
