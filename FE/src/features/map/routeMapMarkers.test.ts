import { describe, expect, it } from 'vitest'
import type { Route } from '../route/types'
import { getRouteEndpointCandidates, routeEndpointPlace, routeLineStyle } from './routeMapMarkers'

const endpoint = (id: string, name: string, lat: number, lng: number) => ({
  id,
  name,
  lat,
  lng,
})

describe('경로 지도 선과 지점', () => {
  it('승차·환승·하차 지점을 만들고 동일 역을 합친다', () => {
    const middle = endpoint('station-2', '환승역', 37.51, 127.04)
    const route: Route = {
      id: 'route',
      label: '최단 경로',
      minutes: 20,
      transfers: 1,
      modes: ['subway'],
      legs: [
        {
          mode: 'walk',
          title: '역까지 이동',
          note: '이동',
          minutes: 2,
          from: endpoint('place', '출발지', 37.5, 127.03),
          to: endpoint('station-1', '승차역', 37.5, 127.03),
        },
        {
          mode: 'subway',
          title: '2호선',
          note: '2호선',
          minutes: 8,
          routeId: '1002',
          from: endpoint('station-1', '승차역', 37.5, 127.03),
          to: middle,
        },
        {
          mode: 'walk',
          transfer: true,
          title: '환승',
          note: '환승',
          minutes: 2,
          from: middle,
          to: middle,
        },
        {
          mode: 'subway',
          title: '6호선',
          note: '6호선',
          minutes: 8,
          routeId: '1006',
          from: middle,
          to: endpoint('station-3', '하차역', 37.52, 127.05),
        },
      ],
    }

    const candidates = getRouteEndpointCandidates(route)
    const rolesById = new Map(
      candidates.map((candidate) => [candidate.endpoint.id, candidate.roles]),
    )
    expect(candidates).toHaveLength(3)
    expect(rolesById.get('station-1')).toEqual(['승차'])
    expect(rolesById.get('station-2')).toEqual(['환승'])
    expect(rolesById.get('station-3')).toEqual(['하차'])
  })

  it('같은 노선으로 나뉜 연속 구간은 환승으로 표시하지 않는다', () => {
    const route: Route = {
      id: 'route',
      label: '최단 경로',
      minutes: 10,
      transfers: 0,
      modes: ['subway'],
      legs: [
        {
          mode: 'subway',
          title: '2호선',
          note: '2호선',
          minutes: 5,
          routeId: '1002',
          from: endpoint('a', '출발역', 37.5, 127.03),
          to: endpoint('b', '중간역', 37.51, 127.04),
        },
        {
          mode: 'subway',
          title: '2호선',
          note: '2호선',
          minutes: 5,
          routeId: '1002',
          from: endpoint('b', '중간역', 37.51, 127.04),
          to: endpoint('c', '도착역', 37.52, 127.05),
        },
      ],
    }

    expect(getRouteEndpointCandidates(route).map(({ roles }) => roles)).toEqual([
      ['승차'],
      ['하차'],
    ])
  })

  it('좌표가 없는 endpoint는 마커 후보에서 생략한다', () => {
    const route: Route = {
      id: 'route',
      label: '최단 경로',
      minutes: 5,
      transfers: 0,
      modes: ['subway'],
      legs: [
        {
          mode: 'subway',
          title: '역',
          note: '역',
          minutes: 5,
          routeId: '1002',
          from: { id: 'missing', name: '좌표 없음' },
          to: endpoint('end', '도착역', 37.52, 127.05),
        },
      ],
    }

    expect(getRouteEndpointCandidates(route)).toEqual([
      expect.objectContaining({ endpoint: expect.objectContaining({ id: 'end' }) }),
    ])
  })

  it('이동수단별 선 스타일과 사용자 표시용 지점 정보를 제공한다', () => {
    expect(routeLineStyle({ mode: 'subway', title: '', note: '', minutes: 1 })).toEqual({
      strokeColor: '#6379bd',
      strokeStyle: 'solid',
    })
    expect(routeLineStyle({ mode: 'bus', title: '', note: '', minutes: 1 })).toEqual({
      strokeColor: '#2f80c0',
      strokeStyle: 'solid',
    })
    expect(routeLineStyle({ mode: 'bike', title: '', note: '', minutes: 1 })).toEqual({
      strokeColor: '#2f7a59',
      strokeStyle: 'solid',
    })
    expect(routeLineStyle({ mode: 'walk', title: '', note: '', minutes: 1 })).toEqual({
      strokeColor: '#7b8591',
      strokeStyle: 'dashed',
    })
    expect(
      routeLineStyle({ mode: 'walk', transfer: true, title: '', note: '', minutes: 1 }),
    ).toEqual({ strokeColor: '#5d6873', strokeStyle: 'dashed' })

    const place = routeEndpointPlace({
      endpoint: endpoint('raw-214', '강변', 37.5, 127.03),
      roles: ['승차'],
    })
    expect(place).toMatchObject({ name: '강변', address: '승차', kind: '승차' })
    expect(place.name).not.toContain('214')
  })
})
