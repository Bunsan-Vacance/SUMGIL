import type { HomeLayer } from './homeLayers'

export default function HomeLayerLegend({ layer }: { layer: HomeLayer | null }) {
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
