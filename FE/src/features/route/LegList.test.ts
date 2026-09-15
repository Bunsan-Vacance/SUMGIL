import { describe, expect, it } from 'vitest'
import { compactLegs } from './LegList'
import type { Leg } from './types'

describe('compactLegs', () => {
  it('groups adjacent same-mode legs for summary display without changing the source legs', () => {
    const legs: Leg[] = [
      { mode: 'bike', title: 'A → B', note: '자전거', minutes: 4, routeId: 'BIKE' },
      { mode: 'bike', title: 'B → C', note: '자전거', minutes: 5, routeId: 'BIKE' },
      { mode: 'walk', title: 'C → D', note: '도보', minutes: 2 },
    ]

    const compact = compactLegs(legs)

    expect(compact).toHaveLength(2)
    expect(compact[0].minutes).toBe(9)
    expect(legs).toHaveLength(3)
    expect(legs[0].minutes).toBe(4)
  })
})
