import { useEffect, useRef, useState } from 'react'

export function useCurrentLocation(
  onPosition: (position: GeolocationPosition) => void,
  onMessage: (message: string) => void,
  scope: string,
) {
  const [locating, setLocating] = useState(false)
  const requestId = useRef(0)
  useEffect(() => {
    setLocating(false)
    return () => {
      requestId.current++
    }
  }, [scope])
  const locate = () => {
    if (!navigator.geolocation) {
      onMessage('이 브라우저에서는 현재 위치를 확인할 수 없어요.')
      return
    }
    const id = ++requestId.current
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (id !== requestId.current) return
        setLocating(false)
        onPosition(position)
      },
      (error) => {
        if (id !== requestId.current) return
        setLocating(false)
        onMessage(
          error.code === 1
            ? '현재 위치를 보려면 위치 권한을 허용해 주세요.'
            : '현재 위치를 확인하지 못했어요. 다시 시도해 주세요.',
        )
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    )
  }
  return { locating, locate }
}
