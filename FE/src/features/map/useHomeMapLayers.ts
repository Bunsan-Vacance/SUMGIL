import { useEffect, useState } from 'react'
import type { Place } from '../route/types'
import type { StationCongestion } from './useNearbyStationCongestion'
import type { HomeLayer } from './homeLayers'

export type HomeSelection =
  { kind: 'bike'; place: Place } | { kind: 'subway'; station: StationCongestion }

/**
 * 홈 지도에서 선택한 대여소·역을 소유한다(App에서 한 번 호출).
 * 레이어는 홈 하단 탭에서 파생해 인자로 받는다. 선택은 한 번에 하나만 가지며,
 * 홈을 벗어나거나(active=false) 레이어가 바뀌면 꺼진 레이어의 선택을 해제한다.
 */
export function useHomeMapLayers(active: boolean, layer: HomeLayer | null) {
  const [selection, setSelection] = useState<HomeSelection | null>(null)
  useEffect(() => {
    if (!active) setSelection(null)
  }, [active])
  useEffect(() => {
    setSelection((current) => {
      if (!current) return current
      if (current.kind === 'bike' && layer !== 'bike') return null
      if (current.kind === 'subway' && layer !== 'crowd') return null
      return current
    })
  }, [layer])
  const selectBikeStation = (place: Place) => {
    if (active && place.kind === '따릉이 대여소') setSelection({ kind: 'bike', place })
  }
  const selectSubwayStation = (station: StationCongestion) => {
    if (active) setSelection({ kind: 'subway', station })
  }
  const clearSelection = () => setSelection(null)
  return { layer, selection, selectBikeStation, selectSubwayStation, clearSelection }
}
