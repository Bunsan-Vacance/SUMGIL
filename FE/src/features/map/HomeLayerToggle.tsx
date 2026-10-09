import { Bike, Users } from 'lucide-react'
import { homeLayerLabels } from './homeLayers'
import type { HomeLayer } from './homeLayers'

interface Props {
  layers: HomeLayer[]
  active: HomeLayer | null
  onChange: (layer: HomeLayer | null) => void
}

const layerIcons = { crowd: Users, bike: Bike } as const

export default function HomeLayerToggle({ layers, active, onChange }: Props) {
  if (!layers.length) return null
  return (
    <div className="home-layer-toggle">
      {layers.map((layer) => {
        const Icon = layerIcons[layer]
        return (
          <button
            key={layer}
            type="button"
            className="home-layer-button"
            aria-label={`${homeLayerLabels[layer]} 레이어`}
            aria-pressed={active === layer}
            onClick={() => onChange(active === layer ? null : layer)}
          >
            <Icon size={18} />
            <span>{homeLayerLabels[layer]}</span>
          </button>
        )
      })}
    </div>
  )
}
