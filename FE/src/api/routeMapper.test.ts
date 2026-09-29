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

  it('leg의 탑승 대기(waitMinutes)를 표시 모델에 보존한다', () => {
    const route = mapBackendRoute(
      response({
        legs: [{ mode: 'SUBWAY', minutes: 10, waitMinutes: 3.5 }],
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.legs[0].waitMinutes).toBe(3.5)
    expect(route.legs[0].minutes).toBe(10)
  })

  it('waitMinutes가 null이면(구형 응답) 필드를 만들지 않는다', () => {
    const route = mapBackendRoute(
      response({
        legs: [{ mode: 'SUBWAY', minutes: 10, waitMinutes: null }],
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.legs[0]).not.toHaveProperty('waitMinutes')
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

  it('LIVE 근거(BUS 실시간)를 수용한다', () => {
    const route = mapBackendRoute(
      response({
        congestionPrediction: {
          congestionPercent: 70,
          congestionGrade: 'MEDIUM',
          dataStatus: 'AVAILABLE',
          predictionBasis: 'LIVE',
        },
      }),
      0,
      '2026-09-17T00:00:00.000Z',
    )

    expect(route.congestionPrediction).toEqual({
      congestionPercent: 70,
      congestionGrade: 'MEDIUM',
      dataStatus: 'AVAILABLE',
      predictionBasis: 'LIVE',
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

  it('transferCount가 없으면 자전거와 대중교통 경계를 포함해 실제 탑승 전환을 센다', () => {
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

    expect(route.transfers).toBe(2)
  })

  it('명시 TRANSFER는 다음 실제 탑승에 한 번만 반영하고 차량 변경과 중복하지 않는다', () => {
    const legs = [
      { mode: 'WALK', minutes: 1 },
      { mode: 'BIKE', minutes: 2 },
      { mode: 'WALK', minutes: 1 },
      { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
      { mode: 'TRANSFER', minutes: 1 },
      { mode: 'SUBWAY', routeId: '1075', minutes: 2 },
      { mode: 'TRANSFER', minutes: 1 },
      { mode: 'SUBWAY', routeId: '1008', minutes: 2 },
    ]

    expect(mapBackendRoute(response({ transferCount: undefined, legs }), 0, '').transfers).toBe(3)
    expect(mapBackendRoute(response({ transferCount: null, legs }), 0, '').transfers).toBe(3)
    expect(mapBackendRoute(response({ transferCount: 3, legs }), 0, '').transfers).toBe(3)
    expect(mapBackendRoute(response({ transferCount: 0, legs }), 0, '').transfers).toBe(0)

    const sameLineTransfer = mapBackendRoute(
      response({
        transferCount: undefined,
        legs: [
          { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
          { mode: 'TRANSFER', minutes: 1 },
          { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
        ],
      }),
      0,
      '',
    )

    expect(sameLineTransfer.transfers).toBe(1)
  })

  it('대중교통에서 자전거로 전환하는 경계도 한 번 센다', () => {
    const route = mapBackendRoute(
      response({
        transferCount: undefined,
        legs: [
          { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
          { mode: 'WALK', minutes: 1 },
          { mode: 'BIKE', routeId: 'bike-a', minutes: 2 },
        ],
      }),
      0,
      '',
    )

    expect(route.transfers).toBe(1)

    const emptyOptions = mapBackendRoute(
      response({
        transferCount: undefined,
        legs: [
          {
            mode: 'BUS',
            routeId: '740',
            minutes: 2,
            routeOptions: [{ routeId: '740' }],
          },
          { mode: 'BUS', routeId: '740', minutes: 2, routeOptions: [] },
        ],
      }),
      0,
      '',
    )

    expect(emptyOptions.transfers).toBe(0)
  })

  it('자전거 구간 사이 도보는 같은 자전거 탑승으로 세고 단독 자전거는 0이다', () => {
    const route = mapBackendRoute(
      response({
        transferCount: undefined,
        legs: [
          { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
          { mode: 'WALK', minutes: 1 },
          { mode: 'BIKE', routeId: 'bike-a', minutes: 2 },
          { mode: 'WALK', minutes: 1 },
          { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
        ],
      }),
      0,
      '',
    )
    const standaloneBike = mapBackendRoute(
      response({ transferCount: undefined, legs: [{ mode: 'BIKE', minutes: 2 }] }),
      0,
      '',
    )

    expect(route.transfers).toBe(2)
    expect(standaloneBike.transfers).toBe(0)
  })

  it('BUS 구간은 누적 공통 노선으로 판단하고 환승 시 현재 집합으로 재설정한다', () => {
    const route = mapBackendRoute(
      response({
        transferCount: undefined,
        legs: [
          {
            mode: 'BUS',
            routeId: 'BUS_CORRIDOR',
            minutes: 2,
            routeOptions: [{ routeId: '108' }, { routeId: '143' }],
          },
          {
            mode: 'BUS',
            routeId: 'BUS_CORRIDOR',
            minutes: 2,
            routeOptions: [{ routeId: '143' }, { routeId: '201' }],
          },
          {
            mode: 'BUS',
            routeId: 'BUS_CORRIDOR',
            minutes: 2,
            routeOptions: [{ routeId: '201' }],
          },
          {
            mode: 'BUS',
            routeId: 'BUS_CORRIDOR',
            minutes: 2,
            routeOptions: [{ routeId: '201' }],
          },
        ],
      }),
      0,
      '',
    )

    expect(route.transfers).toBe(1)
  })

  it('같은 지하철 노선 분할은 0, 다른 노선은 1로 센다', () => {
    const sameLine = mapBackendRoute(
      response({
        transferCount: undefined,
        legs: [
          { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
          { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
        ],
      }),
      0,
      '',
    )
    const differentLine = mapBackendRoute(
      response({
        transferCount: undefined,
        legs: [
          { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
          { mode: 'SUBWAY', routeId: '1008', minutes: 2 },
        ],
      }),
      0,
      '',
    )

    expect(sameLine.transfers).toBe(0)
    expect(differentLine.transfers).toBe(1)
  })

  it('첫 탑승 전과 마지막 탑승 뒤의 TRANSFER는 환승으로 세지 않는다', () => {
    const route = mapBackendRoute(
      response({
        transferCount: undefined,
        legs: [
          { mode: 'TRANSFER', minutes: 1 },
          { mode: 'SUBWAY', routeId: '1003', minutes: 2 },
          { mode: 'TRANSFER', minutes: 1 },
        ],
      }),
      0,
      '',
    )

    expect(route.transfers).toBe(0)
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
