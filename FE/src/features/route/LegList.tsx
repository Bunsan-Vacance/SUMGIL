import type { Route } from './types'
import { modeIcons } from './ModeIcon'
export default function LegList({ route }: { route: Route }) {
  return (
    <ol className="leg-list">
      {route.legs.map((leg, index) => {
        const Icon = modeIcons[leg.mode]
        return (
          <li key={index}>
            <span className={`leg-icon ${leg.mode}`}>
              <Icon size={18} />
            </span>
            <div>
              <strong>{leg.title}</strong>
              <p>{leg.note}</p>
            </div>
            <span>{leg.minutes}분</span>
          </li>
        )
      })}
    </ol>
  )
}
