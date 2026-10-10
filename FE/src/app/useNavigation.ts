import { useCallback, useEffect, useState } from 'react'
import { isOpsViewEnabled } from './opsAccess'

export const screenTitles = {
  home: '숨길 지도 홈',
  browse: '장소 탐색',
  search: '장소 검색',
  results: '추천 경로',
  detail: '선택 경로 상세',
  guide: '길안내',
  arrival: '도착',
  ops: '운영자 뷰',
} as const
export type Screen = keyof typeof screenTitles
export type Navigate = (screen: Screen, query?: string) => void
// '#화면?쿼리'를 화면과 쿼리(물음표 제외)로 나눈다. 쿼리가 없으면 ''.
export function parseHash(
  hash: string,
  opsEnabled = isOpsViewEnabled(),
): { screen: Screen; query: string } {
  const body = hash.slice(1)
  const split = body.indexOf('?')
  const candidate = split === -1 ? body : body.slice(0, split)
  const query = split === -1 ? '' : body.slice(split + 1)
  if (candidate === 'ops') return { screen: opsEnabled ? 'ops' : 'home', query }
  const screen = Object.hasOwn(screenTitles, candidate) ? (candidate as Screen) : 'home'
  return { screen, query }
}
export function parseScreen(hash: string, opsEnabled = isOpsViewEnabled()): Screen {
  return parseHash(hash, opsEnabled).screen
}
const hashFor = (screen: Screen, query?: string) => (query ? `#${screen}?${query}` : `#${screen}`)
export function useNavigation() {
  const [nav, setNav] = useState(() => parseHash(location.hash))
  useEffect(() => {
    const sync = () => setNav(parseHash(location.hash))
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  const go: Navigate = useCallback((next, query) => {
    location.hash = hashFor(next, query)
    setNav({ screen: next, query: query ?? '' })
  }, [])
  const replace: Navigate = useCallback((next, query) => {
    const hash = hashFor(next, query)
    // 같은 해시면 기록을 건드리지 않는다(동기화 effect가 매 렌더 부르지 않게).
    if (hash !== location.hash) history.replaceState(null, '', hash)
    setNav({ screen: next, query: query ?? '' })
  }, [])
  return { screen: nav.screen, query: nav.query, go, replace }
}
