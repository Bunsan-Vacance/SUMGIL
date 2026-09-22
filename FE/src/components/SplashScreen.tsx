import { useEffect } from 'react'

export const SPLASH_DURATION_MS = 2500

interface Props {
  onComplete: () => void
}

export default function SplashScreen({ onComplete }: Props) {
  useEffect(() => {
    const timer = window.setTimeout(onComplete, SPLASH_DURATION_MS)
    return () => window.clearTimeout(timer)
  }, [onComplete])

  return (
    <main className="launch-splash" aria-label="숨길 앱 시작" role="status">
      <div className="launch-splash-content">
        <img src="/icons/icon-512.png" alt="숨길" />
        <h1>빠르게, 여유롭게</h1>
      </div>
    </main>
  )
}
