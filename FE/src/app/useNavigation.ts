import { useCallback, useEffect, useState } from 'react'

export const screenTitles = {
  home: '숨길 지도 홈',
  browse: '장소 탐색',
  search: '장소 검색',
  results: '추천 경로',
  detail: '선택 경로 상세',
  guide: '길안내',
  arrival: '도착',
} as const
export type Screen = keyof typeof screenTitles
export type Navigate = (screen: Screen) => void
export function parseScreen(hash: string): Screen {
  const candidate = hash.slice(1)
  return Object.hasOwn(screenTitles, candidate) ? (candidate as Screen) : 'home'
}
export function useNavigation() {
  const [screen, setScreen] = useState(() => parseScreen(location.hash))
  useEffect(() => {
    const sync = () => setScreen(parseScreen(location.hash))
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  const go: Navigate = useCallback((next) => {
    location.hash = next
    setScreen(next)
  }, [])
  const replace = useCallback((next: Screen) => {
    history.replaceState(null, '', `#${next}`)
    setScreen(next)
  }, [])
  return { screen, go, replace }
}
