import { ChevronRight, Navigation } from 'lucide-react'
import type { Route } from '../route/types'
import { remaining } from '../route/selectors'

export default function ActiveGuidanceBar({
  route,
  step,
  destinationName,
  onResume,
}: {
  route: Route
  step: number
  destinationName: string
  onResume: () => void
}) {
  return (
    <button
      className="active-guidance"
      onClick={onResume}
      aria-label={`${destinationName} 안내로 돌아가기`}
    >
      <Navigation size={22} aria-hidden="true" />
      <span className="active-guidance-copy">
        <strong>
          {destinationName} 안내 중 · {remaining(route, step)}분 남음
        </strong>
        <span>{route.legs[step]?.title}</span>
      </span>
      <ChevronRight size={20} aria-hidden="true" />
    </button>
  )
}
