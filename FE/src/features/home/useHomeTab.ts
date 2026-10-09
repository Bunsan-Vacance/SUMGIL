import { useEffect, useState } from 'react'
import type { HomeLayer } from '../map/homeLayers'
import type { HomeTab } from './HomeTabBar'

/** 탭에서 지도 레이어를 파생한다. 최근기록 탭이나 탭 없음은 레이어가 없다. */
export function tabToLayer(tab: HomeTab | null): HomeLayer | null {
  return tab === 'crowd' || tab === 'bike' ? tab : null
}

/** 홈 하단 탭 상태를 소유한다(App에서 한 번 호출). 홈을 벗어나면 탭을 해제한다. */
export function useHomeTab(active: boolean) {
  const [tab, setTab] = useState<HomeTab | null>(null)
  useEffect(() => {
    if (!active) setTab(null)
  }, [active])
  return { tab, setTab }
}
