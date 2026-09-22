import { useEffect } from 'react'

export const SPLASH_DURATION_MS = 1250

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
        <svg className="launch-splash-icon" viewBox="0 0 512 512" role="img" aria-label="숨길">
          <title>숨길</title>
          <rect width="512" height="512" rx="72" fill="#fff" />
          <path
            d="M154 381l64-65v-64l132-118"
            fill="none"
            stroke="#18b98b"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="44"
          />
          <circle cx="154" cy="381" r="45" fill="#18b98b" />
          <circle cx="350" cy="134" r="67" fill="#18b98b" />
          <circle cx="350" cy="134" r="26" fill="#fff" />
        </svg>
        <h1 aria-label="숨은 길을 찾아 당신의 숨길을 열어 드립니다">
          <span aria-hidden="true">
            숨은 길을 찾아 당신의
            <br />
            숨길을 열어 드립니다
          </span>
        </h1>
      </div>
    </main>
  )
}
