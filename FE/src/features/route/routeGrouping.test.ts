import { describe, expect, it } from 'vitest'
import type { Route } from './types'
import {
  busLabels,
  busLegOptions,
  busOptionCount,
  busOptionLabel,
  busRouteOptions,
  formatBusLabel,
  groupRoutes,
} from './routeGrouping'

const endpoint = (id: string, name = id) => ({ id, name })
function route(id: string, busId: string, busName: string, subwayId = '1002'): Route {
  return {
    id,
    label: '다른 경로',
    minutes: 20,
    transfers: 1,
    modes: ['walk', 'subway', 'bus'],
    legs: [
      {
        mode: 'walk',
        title: '출발 → 역',
        note: '도보',
        minutes: 2,
        from: endpoint('origin'),
        to: endpoint('station'),
      },
      {
        mode: 'subway',
        title: '역 → 환승역',
        note: '2호선',
        routeId: subwayId,
        minutes: 8,
        from: endpoint('station'),
        to: endpoint('transfer'),
      },
      {
        mode: 'bus',
        title: '환승역 → 도착',
        note: busName,
        routeId: busId,
        minutes: 10,
        from: endpoint('transfer'),
        to: endpoint('destination'),
      },
    ],
  }
}

describe('버스 대안 경로 그룹화', () => {
  it('버스 노선만 다른 후보를 묶고 대표 Route를 보존한다', () => {
    const first = route('first', '420-id', '420')
    const second = route('second', 'N26-id', 'N26')
    const groups = groupRoutes([first, second])

    expect(groups).toHaveLength(1)
    expect(groups[0].representative).toBe(first)
    expect(groups[0].variants).toEqual([first, second])
    expect(busRouteOptions(groups[0].variants).map(({ labels }) => labels)).toEqual([
      ['420'],
      ['N26'],
    ])
  })

  it('환승역이나 비버스 노선이 다르면 묶지 않는다', () => {
    const first = route('first', '420-id', '420')
    const differentSubway = route('different-subway', 'N26-id', 'N26', '1005')
    const differentEndpoint = {
      ...route('different-endpoint', 'N13-id', 'N13'),
      legs: route('different-endpoint', 'N13-id', 'N13').legs.map((leg, index) =>
        index === 2 ? { ...leg, to: endpoint('other-destination') } : leg,
      ),
    }

    expect(groupRoutes([first, differentSubway, differentEndpoint])).toHaveLength(3)
  })

  it('endpoint identity가 없으면 보수적으로 묶지 않는다', () => {
    const first = route('first', '420-id', '420')
    const missingEndpoint = {
      ...route('missing', 'N26-id', 'N26'),
      legs: route('missing', 'N26-id', 'N26').legs.map((leg, index) =>
        index === 2 ? { ...leg, to: undefined } : leg,
      ),
    }

    expect(groupRoutes([first, missingEndpoint])).toHaveLength(2)
  })

  it('버스 번호를 표시용으로 정리하고 같은 번호 선택지는 한 번만 노출한다', () => {
    const first = route('first', '420-id', '420')
    const duplicate = route('duplicate', '420-id', '420')

    expect(formatBusLabel('420')).toBe('420번')
    expect(busLabels(first)).toEqual(['420'])
    expect(busRouteOptions([first, duplicate])).toHaveLength(1)
  })

  it('BUS leg 내부 선택지는 경로 후보와 분리해 표시용으로 읽는다', () => {
    const current = route('current', 'BUS', '버스')
    current.legs[2].busRouteOptions = [
      { routeId: '420', routeName: '420번', headwayMin: 8 },
      { routeId: 'N26' },
    ]

    expect(busLegOptions(current)).toEqual([
      {
        leg: current.legs[2],
        index: 2,
        options: current.legs[2].busRouteOptions,
      },
    ])
    expect(busOptionCount(current)).toBe(2)
    expect(busOptionLabel(current.legs[2].busRouteOptions[0])).toBe('420번')
    expect(busOptionLabel(current.legs[2].busRouteOptions[1])).toBe('N26')
  })
})
