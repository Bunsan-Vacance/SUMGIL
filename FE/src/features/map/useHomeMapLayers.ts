import { useState } from 'react'
import type { Place } from '../route/types'
import type { HomeLayer } from './homeLayers'

export function useHomeMapLayers(initialLayer: HomeLayer | null = 'bike') {
  const [layer, setLayerState] = useState<HomeLayer | null>(initialLayer)
  const [selectedStation, setSelectedStation] = useState<Place | null>(null)
  const setLayer = (next: HomeLayer | null) => {
    setLayerState(next)
    // 따릉이 레이어를 끄면 선택한 대여소도 함께 해제한다.
    if (next !== 'bike') setSelectedStation(null)
  }
  const selectStation = (place: Place) => {
    if (place.kind === '따릉이 대여소') setSelectedStation(place)
  }
  const clearStation = () => setSelectedStation(null)
  return { layer, setLayer, selectedStation, selectStation, clearStation }
}
