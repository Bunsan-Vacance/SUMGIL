import { describe, expect, it } from 'vitest'
import { RepositoryError } from './errors'
import { mapBackendRoute } from './routeMapper'

const response = (overrides: Record<string, unknown> = {}) => ({
  routeType: 'SHORTEST',
  totalMinutes: 10,
  source: 'ALGORITHM',
  transferCount: 0,
  legs: [{ mode: 'WALK', minutes: 10, distanceMeters: 500 }],
  ...overrides,
})

describe('경로 응답 확장 필드', () => {
  it('BUS leg의 노선 선택지와 배차간격을 표시 모델에 보존한다', () => {
    const route = mapBackendRoute(
      response({
        legs: [
          {
            mode: 'BUS',
            routeId: 'BUS',
            routeName: null,
            minutes: 10,
            routeOptions: [
              { routeId: '108', routeName: '108번', headwayMin: 10 },
              { routeId: '143', routeName: null, headwayMin: null },
            ],
          },
        ],
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.legs[0]).toMatchObject({
      routeId: 'BUS',
      note: '108번 · 143',
      busRouteOptions: [{ routeId: '108', routeName: '108번', headwayMin: 10 }, { routeId: '143' }],
    })
  })

  it.each([
    { mode: 'SUBWAY', routeOptions: [] },
    { mode: 'BUS', routeOptions: {} },
    { mode: 'BUS', routeOptions: [{ routeName: '108번' }] },
    { mode: 'BUS', routeOptions: [{ routeId: '108', routeName: ' ' }] },
    { mode: 'BUS', routeOptions: [{ routeId: '108', headwayMin: 0 }] },
    {
      mode: 'BUS',
      routeOptions: [{ routeId: '108' }, { routeId: '108', routeName: '108번' }],
    },
  ])('잘못된 버스 노선 선택지를 거부한다: %#', ({ mode, routeOptions }) => {
    expect(() =>
      mapBackendRoute(
        response({ legs: [{ mode, minutes: 10, routeOptions }] }),
        0,
        '2026-09-17T00:00:00.000Z',
      ),
    ).toThrow(RepositoryError)
  })

  it('leg 혼잡도 수치를 내부 구간 필드로 보존하고 100 초과도 허용한다', () => {
    const route = mapBackendRoute(
      response({
        legs: [{ mode: 'SUBWAY', minutes: 10, congestionLevel: 120.5 }],
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.legs[0].segmentCongestionLevel).toBe(120.5)
  })

  it('서버 구간 등급을 보존하고 숫자 기반 등급보다 우선하도록 함께 매핑한다', () => {
    const route = mapBackendRoute(
      response({
        legs: [
          { mode: 'BUS', minutes: 5, congestionLevel: 80, congestionGrade: 'NORMAL' },
          { mode: 'SUBWAY', minutes: 5, congestionGrade: 'SATURATED' },
        ],
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(
      route.legs.map((leg) => [leg.segmentCongestionLevel, leg.segmentCongestionGrade]),
    ).toEqual([
      [80, 'NORMAL'],
      [undefined, 'SATURATED'],
    ])
  })

  it.each(['LOW', 'MEDIUM', 'HIGH', 'UNKNOWN'])(
    '지원하지 않는 구간 등급을 거부한다: %s',
    (grade) => {
      expect(() =>
        mapBackendRoute(
          response({ legs: [{ mode: 'BUS', minutes: 10, congestionGrade: grade }] }),
          0,
          '2026-09-17T00:00:00.000Z',
        ),
      ).toThrow(RepositoryError)
    },
  )

  it('도보·자전거 구간의 혼잡도 수치는 표시 모델에 넣지 않는다', () => {
    const route = mapBackendRoute(
      response({
        legs: [
          { mode: 'WALK', minutes: 5, congestionLevel: 20 },
          { mode: 'BIKE', minutes: 5, congestionLevel: 80 },
        ],
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.legs.map((leg) => leg.segmentCongestionLevel)).toEqual([undefined, undefined])
  })

  it.each([-1, Number.NaN, Number.POSITIVE_INFINITY, '80', {}])(
    '잘못된 leg 혼잡도 수치를 거부한다: %#',
    (congestionLevel) => {
      expect(() =>
        mapBackendRoute(
          response({ legs: [{ mode: 'SUBWAY', minutes: 10, congestionLevel }] }),
          0,
          '2026-09-17T00:00:00.000Z',
        ),
      ).toThrow(RepositoryError)
    },
  )

  it('혼잡도 예측 객체와 source를 보존한다', () => {
    const route = mapBackendRoute(
      response({
        source: 'MOCK',
        congestionPrediction: {
          congestionPercent: 0,
          congestionGrade: 'LOW',
          dataStatus: 'AVAILABLE',
          predictionBasis: 'RECENT_7D',
        },
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.source).toBe('MOCK')
    expect(route.congestionPrediction).toEqual({
      congestionPercent: 0,
      congestionGrade: 'LOW',
      dataStatus: 'AVAILABLE',
      predictionBasis: 'RECENT_7D',
    })
  })

  it.each([
    {
      congestionPercent: -1,
      congestionGrade: 'LOW',
      dataStatus: 'AVAILABLE',
      predictionBasis: null,
    },
    {
      congestionPercent: 50,
      congestionGrade: 'UNKNOWN',
      dataStatus: 'AVAILABLE',
      predictionBasis: null,
    },
    { congestionPercent: 50, congestionGrade: null, dataStatus: 'UNKNOWN', predictionBasis: null },
    {
      congestionPercent: 50,
      congestionGrade: null,
      dataStatus: 'NO_LOOKUP',
      predictionBasis: 'UNKNOWN',
    },
    {
      congestionPercent: 50,
      congestionGrade: null,
      dataStatus: 'NO_LOOKUP',
      predictionBasis: null,
    },
    {
      congestionPercent: null,
      congestionGrade: 'LOW',
      dataStatus: 'NO_LOOKUP',
      predictionBasis: null,
    },
  ])('잘못된 혼잡도 예측 응답을 거부한다: %#', (congestionPrediction) => {
    expect(() =>
      mapBackendRoute(response({ congestionPrediction }), 0, '2026-09-17T00:00:00.000Z'),
    ).toThrow(RepositoryError)
  })

  it('100을 넘는 유한 수치와 null을 그대로 보존한다', () => {
    expect(
      mapBackendRoute(
        response({
          congestionPrediction: {
            congestionPercent: 120.1,
            congestionGrade: 'HIGH',
            dataStatus: 'AVAILABLE',
            predictionBasis: 'RECENT_7D',
          },
        }),
        0,
        '2026-09-17T00:00:00.000Z',
      ).congestionPrediction,
    ).toEqual({
      congestionPercent: 120.1,
      congestionGrade: 'HIGH',
      dataStatus: 'AVAILABLE',
      predictionBasis: 'RECENT_7D',
    })
  })

  it('transitionType을 표시용으로 보존하고 명시된 transferCount 0을 우선한다', () => {
    const route = mapBackendRoute(
      response({
        legs: [
          {
            mode: 'TRANSFER',
            transitionType: 'BOARDING',
            fromNodeName: '정류장',
            minutes: 1,
          },
          { mode: 'BUS', routeId: '740', minutes: 9 },
        ],
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.transfers).toBe(0)
    expect(route.legs[0]).toMatchObject({
      transfer: false,
      transitionType: 'BOARDING',
      title: '정류장에서 승차',
    })
  })

  it('transferCount가 없으면 transit 노선 변경만 환승으로 세고 자전거 경계는 세지 않는다', () => {
    const route = mapBackendRoute(
      response({
        transferCount: undefined,
        legs: [
          { mode: 'WALK', routeId: 'WALK', minutes: 2 },
          { mode: 'BIKE', routeId: 'BIKE', minutes: 3 },
          { mode: 'WALK', routeId: 'WALK', minutes: 2 },
          { mode: 'BUS', routeId: '740', minutes: 3 },
          { mode: 'SUBWAY', routeId: '1002', minutes: 5 },
        ],
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.transfers).toBe(1)
  })

  it('자전거 endpoint의 명시 rental ID를 node ID와 구분해 보존한다', () => {
    const route = mapBackendRoute(
      response({
        legs: [
          {
            mode: 'BIKE',
            minutes: 10,
            fromNodeId: 'node-a',
            fromRentalId: 'rental-a',
            toNodeId: 'node-b',
            toRentalId: 'rental-b',
          },
        ],
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.legs[0]).toMatchObject({
      from: { id: 'node-a', rentalId: 'rental-a' },
      to: { id: 'node-b', rentalId: 'rental-b' },
    })
  })
})
