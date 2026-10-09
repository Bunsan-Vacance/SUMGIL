import { SEGMENT_CONGESTION_LEVELS } from '../route/segmentCongestion'
import type { HomeLayer } from './homeLayers'

export default function HomeLayerLegend({ layer }: { layer: HomeLayer | null }) {
  if (layer === 'crowd') {
    return (
      <div className="home-layer-legend">
        <strong>지금 역 혼잡도</strong>
        {SEGMENT_CONGESTION_LEVELS.map((level) => (
          <span key={level.grade}>
            <i className="legend-dot" style={{ background: level.color }} />
            {level.label}
          </span>
        ))}
        <span>
          <i className="legend-dot" style={{ background: '#82909b' }} />
          정보 없음
        </span>
      </div>
    )
  }
  if (layer !== 'bike') return null
  return (
    <div className="home-layer-legend">
      <strong>따릉이 대여 가능 대수</strong>
      <span>
        <i className="legend-dot level-ok" />
        3대 이상
      </span>
      <span>
        <i className="legend-dot level-low" />
        2대 이하
      </span>
    </div>
  )
}
