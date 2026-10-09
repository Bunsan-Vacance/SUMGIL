import { Bike, Clock, Users } from 'lucide-react'

export type HomeTab = 'recent' | 'crowd' | 'bike'

interface Props {
  active: HomeTab | null
  onChange: (tab: HomeTab | null) => void
  disabled?: HomeTab[]
}

const tabs = [
  { tab: 'recent', label: '최근기록', Icon: Clock },
  { tab: 'crowd', label: '혼잡도', Icon: Users },
  { tab: 'bike', label: '자전거', Icon: Bike },
] as const

/** 홈 하단 탭 바. 활성 탭을 다시 누르면 선택을 해제한다. */
export default function HomeTabBar({ active, onChange, disabled = [] }: Props) {
  return (
    <nav className="home-tabbar" aria-label="홈 하단 탭">
      {tabs.map(({ tab, label, Icon }) => (
        <button
          key={tab}
          type="button"
          aria-pressed={active === tab}
          disabled={disabled.includes(tab)}
          onClick={() => onChange(active === tab ? null : tab)}
        >
          <Icon size={20} aria-hidden="true" />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  )
}
