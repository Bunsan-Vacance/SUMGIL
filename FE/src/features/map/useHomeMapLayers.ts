import { useEffect, useState } from 'react'
import type { NearbyStation } from '../../api/contracts'
import type { Place } from '../route/types'
import { availableLayers } from './homeLayers'
import type { HomeLayer } from './homeLayers'

export type HomeSelection =
  { kind: 'bike'; place: Place } | { kind: 'subway'; station: NearbyStation }

/**
 * 홈 지도의 레이어 선택과 선택한 대여소·역을 소유한다(App에서 한 번 호출).
 * 레이어는 화면을 오가도 유지하고, 선택은 홈을 벗어나면(active=false) 해제한다.
 * 선택은 한 번에 하나만 가진다.
 */
export function useHomeMapLayers(
  active = true,
  initialLayer: HomeLayer | null = availableLayers[0] ?? null,
) {
  const [layer, setLayerState] = useState<HomeLayer | null>(initialLayer)
  const [selection, setSelection] = useState<HomeSelection | null>(null)
  useEffect(() => {
    if (!active) setSelection(null)
  }, [active])
  const setLayer = (next: HomeLayer | null) => {
    setLayerState(next)
    // 꺼진 레이어의 선택은 함께 해제한다.
    setSelection((current) => {
      if (!current) return current
      if (current.kind === 'bike' && next !== 'bike') return null
      if (current.kind === 'subway' && next !== 'crowd') return null
      return current
    })
  }
  const selectBikeStation = (place: Place) => {
    if (active && place.kind === '따릉이 대여소') setSelection({ kind: 'bike', place })
  }
  const selectSubwayStation = (station: NearbyStation) => {
    if (active) setSelection({ kind: 'subway', station })
  }
  const clearSelection = () => setSelection(null)
  return { layer, setLayer, selection, selectBikeStation, selectSubwayStation, clearSelection }
}
