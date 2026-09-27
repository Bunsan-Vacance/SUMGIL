// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { RepositoryError } from './errors'
import {
  buildRerouteRequest,
  createBackendRerouteRepository,
  proposalToRoute,
  type RerouteCheckRequest,
} from './reroute'
import { mockRerouteRepository, rerouteProposalFixture } from './mock/reroute'
import { initialGuidance, type GuidanceState } from '../features/guidance/guidanceReducer'
import type { Place, Route } from '../features/route/types'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

const baseRoute: Route = {
  id: 'r1',
  label: '경로',
  minutes: 18,
  transfers: 0,
  modes: ['walk', 'subway', 'walk', 'bike', 'walk'],
  legs: [
    {
      mode: 'walk',
      title: '역으로 이동',
      note: '',
      minutes: 3,
      from: { id: 'origin' },
      to: { id: 'yeoksam', lat: 37.5, lng: 127.0 },
    },
    {
      mode: 'subway',
      title: '지하철 이동',
      note: '',
      minutes: 5,
      routeId: '1002',
      from: { id: 'yeoksam', lat: 37.5, lng: 127.0 },
      to: { id: 'seolleung', lat: 37.504, lng: 127.048 },
    },
    {
      mode: 'walk',
      title: '대여소로 이동',
      note: '',
      minutes: 2,
      from: { id: 'ND-221', lat: 37.5045, lng: 127.049 },
      to: { id: 'rental-a', rentalId: 'ST-1', lat: 37.505, lng: 127.05 },
    },
    {
      mode: 'bike',
      title: '따릉이 이동',
      note: '',
      minutes: 6,
      from: { id: 'rental-a', rentalId: 'ST-1' },
      to: { id: 'rental-b', rentalId: 'ST-2' },
    },
    { mode: 'walk', title: '도착', note: '', minutes: 2 },
  ],
}
const destination: Place = {
  id: 'dogok',
  name: '도곡역',
  address: '',
  kind: '역',
  stationId: 'dogok',
}
const baseState: GuidanceState = {
  ...initialGuidance,
  route: baseRoute,
  destination,
  step: 1,
}

describe('buildRerouteRequest — 호출 조건', () => {
  it('조건을 모두 만족하면 요청과 legIndex를 반환한다', () => {
    const result = buildRerouteRequest(baseState, 'sess-1', { debugForce: false })
    expect(result).toEqual({
      request: {
        sessionId: 'sess-1',
        step: 1,
        rentalId: 'ST-1',
        etaToRentalMinutes: 7,
        destStationId: 'dogok',
        boundary: { legIndex: 2, nodeId: 'ND-221', lat: 37.5045, lng: 127.049 },
      },
      legIndex: 2,
    })
  })

  it('debugForce가 true면 요청에 debugForceTrigger를 싣는다', () => {
    const result = buildRerouteRequest(baseState, 'sess-1', { debugForce: true })
    expect(result?.request.debugForceTrigger).toBe(true)
  })

  it('안내가 완료되면 호출하지 않는다', () => {
    expect(
      buildRerouteRequest({ ...baseState, completed: true }, 'sess-1', { debugForce: false }),
    ).toBeNull()
  })

  it('현재 구간이 지하철이 아니면 호출하지 않는다', () => {
    expect(
      buildRerouteRequest({ ...baseState, step: 0 }, 'sess-1', { debugForce: false }),
    ).toBeNull()
  })

  it('목적지 역 ID가 없으면 좌표가 있어도 호출하지 않는다', () => {
    const noStationId = { ...destination, stationId: undefined, lat: 37.49, lng: 127.03 }
    expect(
      buildRerouteRequest({ ...baseState, destination: noStationId }, 'sess-1', {
        debugForce: false,
      }),
    ).toBeNull()
  })

  it('경로 어디에도 대여소로 이어지는 구간이 없으면 호출하지 않는다', () => {
    const noRental: Route = {
      ...baseRoute,
      legs: baseRoute.legs.map((leg, index) =>
        index === 2
          ? { ...leg, to: { ...leg.to!, rentalId: undefined } }
          : index === 3
            ? { ...leg, from: { ...leg.from!, rentalId: undefined } }
            : leg,
      ),
    }
    expect(
      buildRerouteRequest({ ...baseState, route: noRental }, 'sess-1', { debugForce: false }),
    ).toBeNull()
  })

  it('경계 leg의 출발 좌표가 없으면 추측하지 않고 호출하지 않는다', () => {
    const noCoordinate: Route = {
      ...baseRoute,
      legs: baseRoute.legs.map((leg, index) =>
        index === 2 ? { ...leg, from: { id: leg.from!.id } } : leg,
      ),
    }
    expect(
      buildRerouteRequest({ ...baseState, route: noCoordinate }, 'sess-1', { debugForce: false }),
    ).toBeNull()
  })

  it('이미 경계 구간을 지났으면(step >= legIndex) 호출하지 않는다', () => {
    expect(
      buildRerouteRequest({ ...baseState, step: 2 }, 'sess-1', { debugForce: false }),
    ).toBeNull()
  })
})

describe('재안내 확인 응답 검증', () => {
  it('허용되지 않은 status는 거부한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ status: 'UNKNOWN' }) })),
    )
    await expect(
      createBackendRerouteRepository('http://ai.test').check(
        mockRequest(),
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it.each(['no_trigger', 'no_alternative', 'unavailable'] as const)(
    '%s 상태는 status·reason만 남기고 통과시킨다',
    async (status) => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => ({
          ok: true,
          status: 200,
          json: async () => ({ status, reason: 'below_threshold', target: { rentalId: 'X' } }),
        })),
      )
      await expect(
        createBackendRerouteRepository('http://ai.test').check(
          mockRequest(),
          new AbortController().signal,
        ),
      ).resolves.toEqual({ status, reason: 'below_threshold' })
    },
  )

  it.each(['recommendationId', 'walkLeg', 'boundary', 'alternative'])(
    'proposal 응답에 %s가 없으면 거부한다',
    async (missingField) => {
      const body: Record<string, unknown> = { ...proposalResponseBody() }
      delete body[missingField]
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => ({ ok: true, status: 200, json: async () => body })),
      )
      await expect(
        createBackendRerouteRepository('http://ai.test').check(
          mockRequest(),
          new AbortController().signal,
        ),
      ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
    },
  )

  it('route.legs가 빈 배열이면 거부한다', async () => {
    const body = { ...proposalResponseBody(), route: { ...proposalResponseBody().route, legs: [] } }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => body })),
    )
    await expect(
      createBackendRerouteRepository('http://ai.test').check(
        mockRequest(),
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('유효한 proposal 응답은 그대로 파싱한다', async () => {
    const body = proposalResponseBody()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => body })),
    )
    await expect(
      createBackendRerouteRepository('http://ai.test').check(
        mockRequest(),
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({
      status: 'proposal',
      recommendationId: body.recommendationId,
      alternative: body.alternative,
      boundary: body.boundary,
    })
  })
})

describe('proposalToRoute', () => {
  it('walkLeg를 앞에 붙인 잔여 경로를 만들고 estimated 도보 구간의 geometry를 보존한다', () => {
    const route = proposalToRoute(rerouteProposalFixture, '2026-09-23T09:00:00+09:00')
    expect(route.id).toBe(`reroute:${rerouteProposalFixture.recommendationId}`)
    expect(route.label).toBe('재안내 경로')
    expect(route.legs).toHaveLength(2)
    expect(route.legs[0]).toMatchObject({ mode: 'walk' })
    expect(route.legs[0].geometry).toBeDefined()
    expect(route.legs[1]).toMatchObject({ mode: 'bike' })
  })

  it('proposal 상태가 아니면 거부한다', () => {
    expect(() => proposalToRoute({ status: 'no_trigger' }, '2026-09-23T09:00:00+09:00')).toThrow(
      RepositoryError,
    )
  })

  it('route.legs가 없으면 거부한다', () => {
    const malformedRoute = {
      ...(rerouteProposalFixture.route as Record<string, unknown>),
      legs: undefined,
    }
    expect(() =>
      proposalToRoute(
        { ...rerouteProposalFixture, route: malformedRoute },
        '2026-09-23T09:00:00+09:00',
      ),
    ).toThrow(RepositoryError)
  })
})

describe('mock 재안내 확인', () => {
  it.each(['no_trigger', 'no_alternative', 'unavailable', 'proposal'] as const)(
    '%s 상태를 반환한다',
    async (statusKey) => {
      vi.stubEnv('VITE_REROUTE_MOCK_STATUS', statusKey)
      const result = await mockRerouteRepository.check(mockRequest(), new AbortController().signal)
      expect(result.status).toBe(statusKey)
    },
  )

  it('proposal 응답은 요청의 rentalId·boundary를 그대로 에코한다', async () => {
    vi.stubEnv('VITE_REROUTE_MOCK_STATUS', 'proposal')
    const request = mockRequest()
    const result = await mockRerouteRepository.check(request, new AbortController().signal)
    expect(result.target?.rentalId).toBe(request.rentalId)
    expect(result.boundary).toEqual(request.boundary)
  })
})

function mockRequest(): RerouteCheckRequest {
  return {
    sessionId: 'sess-1',
    step: 1,
    rentalId: 'ST-REQ',
    etaToRentalMinutes: 8,
    destStationId: 'dogok',
    boundary: { legIndex: 2, nodeId: 'ND-REQ', lat: 37.1, lng: 127.1 },
  }
}

function proposalResponseBody() {
  return {
    status: 'proposal',
    recommendationId: 'reco-1',
    validUntil: '2026-09-23T09:10:00+09:00',
    recommendedBy: 'AGENT',
    reason: '대안 대여소가 더 여유로워요.',
    target: { rentalId: 'ST-TARGET' },
    alternative: {
      rentalId: 'ST-ALT',
      name: '대안 대여소',
      lat: 37.5,
      lng: 127.0,
      distanceMeters: 100,
    },
    boundary: { legIndex: 1, nodeId: 'ND-1', lat: 37.5, lng: 127.0 },
    walkLeg: {
      mode: 'WALK',
      fromNodeId: 'ND-1',
      fromLat: 37.5,
      fromLng: 127.0,
      toNodeId: 'ST-ALT',
      toLat: 37.501,
      toLng: 127.001,
      minutes: 1,
      geometryStatus: 'estimated',
      estimated: true,
    },
    route: {
      routeType: 'BIKE_SUBWAY',
      totalMinutes: 10,
      source: 'ALGORITHM',
      legs: [{ mode: 'BIKE', minutes: 10, fromNodeId: 'ST-ALT' }],
    },
  }
}
