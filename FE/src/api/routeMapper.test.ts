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
