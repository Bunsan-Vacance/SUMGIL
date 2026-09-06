import { ArrowRight, Pencil, Search } from 'lucide-react'
import type { Place } from '../features/route/types'
interface Props {
  origin: Place
  destination: Place | null
  openSearch: (target: 'origin' | 'destination') => void
  findRoutes: () => void
}
export default function HomePage({ origin, destination, openSearch, findRoutes }: Props) {
  return (
    <>
      <div className="brand">
        <span>숨</span>
        <b>숨길</b>
      </div>
      <section className="home-panel">
        <h2>어디로 갈까요?</h2>
        <div className="trip-fields">
          <button onClick={() => openSearch('origin')}>
            <span className="dot start" />
            <small>출발</small>
            <strong>{origin.name}</strong>
            <Pencil size={16} />
          </button>
          <button onClick={() => openSearch('destination')}>
            <span className="dot end" />
            <small>도착</small>
            <strong className={!destination ? 'muted' : ''}>
              {destination?.name || '도착지를 검색하세요'}
            </strong>
            <Search size={17} />
          </button>
        </div>
        <button className="primary" onClick={() => findRoutes()}>
          경로 찾기
          <ArrowRight size={18} />
        </button>
      </section>
    </>
  )
}
