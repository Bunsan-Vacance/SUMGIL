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

  it('명시된 구간 전환 유형을 지도 지점 역할로 사용한다', () => {
    const station = endpoint('station', '환승역', 37.51, 127.04)
    const route: Route = {
      id: 'route',
      label: '경로',
      minutes: 12,
      transfers: 1,
      modes: ['subway'],
      legs: [
        {
          mode: 'walk',
          title: '출발지에서 승차',
          note: '승차',
          minutes: 1,
          transitionType: 'BOARDING',
          from: endpoint('origin', '출발지', 37.5, 127.03),
          to: station,
        },
        {
          mode: 'walk',
          title: '환승역에서 환승',
          note: '환승',
          minutes: 2,
          transitionType: 'TRANSFER',
          from: station,
          to: station,
        },
        {
          mode: 'walk',
          title: '환승역에서 하차',
          note: '하차',
          minutes: 1,
          transitionType: 'ALIGHTING',
          from: station,
          to: endpoint('destination', '도착지', 37.52, 127.05),
        },
      ],
    }

    const candidates = getRouteEndpointCandidates(route)
    const stationCandidate = candidates.find(({ endpoint: value }) => value.id === 'station')
    expect(stationCandidate?.roles).toEqual(['환승'])
    expect(stationCandidate?.bikeRoles).toBeUndefined()
    expect(candidates.find(({ endpoint: value }) => value.id === 'origin')?.roles).toEqual(['승차'])
    expect(candidates.find(({ endpoint: value }) => value.id === 'destination')?.roles).toEqual([
      '하차',
    ])
  })

  it('명시된 대여·반납 ID를 따릉이 장소에 그대로 보존한다', () => {
    const route: Route = {
      id: 'bike-route',
      label: '자전거 경로',
      minutes: 8,
      transfers: 0,
      modes: ['bike'],
      legs: [
        {
          mode: 'bike',
          title: '자전거 이동',
          note: '자전거',
          minutes: 8,
          from: { ...endpoint('node-a', '대여소', 37.5, 127.03), rentalId: 'rental-a' },
          to: { ...endpoint('node-b', '반납소', 37.52, 127.05), rentalId: 'rental-b' },
        },
      ],
    }

    const candidate = getRouteEndpointCandidates(route).find(
      ({ endpoint: value }) => value.id === 'node-a',
    )
    expect(routeEndpointPlace(candidate!).rentalId).toBe('rental-a')
  })

  it('연속된 자전거 구간은 대여·반납 경계만 표시한다', () => {
    const rental = endpoint('bike-rental', '대여소', 37.5, 127.03)
    const middle = endpoint('bike-middle', '중간 지점', 37.51, 127.04)
    const returned = endpoint('bike-return', '반납소', 37.52, 127.05)
    const route: Route = {
      id: 'bike-route',
      label: '따릉이 경로',
      minutes: 12,
      transfers: 0,
      modes: ['walk', 'bike'],
      legs: [
        { mode: 'walk', title: '대여소까지 이동', note: '', minutes: 1, to: rental },
        { mode: 'bike', title: '자전거 이동', note: '', minutes: 4, from: rental, to: middle },
        { mode: 'bike', title: '자전거 이동', note: '', minutes: 4, from: middle, to: returned },
        { mode: 'walk', title: '목적지까지 이동', note: '', minutes: 3, from: returned },
      ],
    }

    const candidates = getRouteEndpointCandidates(route)
    expect(candidates.map(({ endpoint, bikeRoles }) => [endpoint.id, bikeRoles])).toEqual([
      ['bike-rental', ['대여']],
      ['bike-return', ['반납']],
    ])
    expect(candidates.some(({ endpoint }) => endpoint.id === 'bike-middle')).toBe(false)
  })

  it('자전거 반납 지점에 겹친 승차 역할은 자전거 표시에 흡수한다', () => {
    const station = endpoint('station', '환승역 대여소', 37.51, 127.04)
    const route: Route = {
      id: 'bike-transit-route',
      label: '따릉이 포함 경로',
      minutes: 10,
      transfers: 0,
      modes: ['bike', 'subway'],
      legs: [
        {
          mode: 'bike',
          title: '따릉이 이동',
          note: '',
          minutes: 4,
          from: endpoint('rental', '출발 대여소', 37.5, 127.03),
          to: station,
        },
        {
          mode: 'subway',
          title: '지하철 이동',
          note: '',
          minutes: 6,
          from: station,
          to: endpoint('destination', '도착역', 37.52, 127.05),
        },
      ],
    }

    const candidate = getRouteEndpointCandidates(route).find(
      ({ endpoint }) => endpoint.id === 'station',
    )
    expect(candidate).toMatchObject({ roles: ['승차'], bikeRoles: ['반납'] })
    expect(routeEndpointPlace(candidate!).address).toBe('따릉이 반납')
    expect(routeEndpointPlace(candidate!).kind).toBe('따릉이 대여소')
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
      strokeColor: '#28323c',
      strokeStyle: 'solid',
    })
    expect(routeLineStyle({ mode: 'bus', title: '', note: '', minutes: 1 })).toEqual({
      strokeColor: '#28323c',
      strokeStyle: 'solid',
    })
    expect(routeLineStyle({ mode: 'bike', title: '', note: '', minutes: 1 })).toEqual({
      strokeColor: '#28323c',
      strokeStyle: 'solid',
    })
    expect(routeLineStyle({ mode: 'walk', title: '', note: '', minutes: 1 })).toEqual({
      strokeColor: '#28323c',
      strokeStyle: 'solid',
    })
    expect(
      routeLineStyle({ mode: 'walk', transfer: true, title: '', note: '', minutes: 1 }),
    ).toEqual({ strokeColor: '#28323c', strokeStyle: 'dashed' })
    expect(
      routeLineStyle({
        mode: 'walk',
        title: '',
        note: '',
        minutes: 1,
        segmentCongestionLevel: 110,
      }),
    ).toEqual({ strokeColor: '#28323c', strokeStyle: 'solid' })
    expect(
      [20, 50, 80, 110].map(
        (level) =>
          routeLineStyle({
            mode: 'subway',
            title: '',
            note: '',
            minutes: 1,
            segmentCongestionLevel: level,
          }).strokeColor,
      ),
    ).toEqual(['#1d4ed8', '#15803d', '#b91c1c', '#7e22ce'])

    const place = routeEndpointPlace({
      endpoint: endpoint('raw-214', '강변', 37.5, 127.03),
      roles: ['승차'],
    })
    expect(place).toMatchObject({ name: '강변', address: '승차', kind: '승차' })
    expect(place.name).not.toContain('214')
  })
})
