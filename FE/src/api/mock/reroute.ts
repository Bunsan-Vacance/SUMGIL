import type { RerouteCheckResponse, RerouteRepository, RerouteStatus } from '../reroute'

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timer = setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })
}

// AI/app/TIME/fixtures/reroute_check_*.json의 response 부를 그대로 옮긴 값이다(S15P21A104-323-3).
// recommendationId·validUntil은 fixture 고정값이라 실제 응답과 다르다(fixtures/README.md 참고).
export const rerouteNoTriggerFixture: RerouteCheckResponse = {
  status: 'no_trigger',
  recommendationId: null,
  validUntil: null,
  recommendedBy: null,
  reason: 'below_threshold',
  target: null,
  alternative: null,
  boundary: null,
  walkLeg: null,
  route: null,
}

export const rerouteNoAlternativeFixture: RerouteCheckResponse = {
  status: 'no_alternative',
  recommendationId: null,
  validUntil: null,
  recommendedBy: null,
  reason: 'no_nearby_station',
  target: null,
  alternative: null,
  boundary: null,
  walkLeg: null,
  route: null,
}

export const rerouteUnavailableFixture: RerouteCheckResponse = {
  status: 'unavailable',
  recommendationId: null,
  validUntil: null,
  recommendedBy: null,
  reason: 'target_unknown',
  target: null,
  alternative: null,
  boundary: null,
  walkLeg: null,
  route: null,
}

export const rerouteProposalFixture: RerouteCheckResponse = {
  status: 'proposal',
  recommendationId: '00000000-0000-0000-0000-000000000000',
  validUntil: '2026-09-23T09:10:00+09:00',
  recommendedBy: 'AGENT',
  reason: '교대 대여소는 거리가 가깝고 자전거도 넉넉합니다.',
  target: {
    rentalId: 'ST-TARGET',
    name: '역삼',
    currentBikes: 0,
    predictedStock: 0.3,
    pEmpty: 0.9,
    horizonMin: 10,
  },
  alternative: {
    rentalId: 'ST-ALT-A',
    name: '교대',
    lat: 37.5666,
    lng: 126.978,
    distanceMeters: 11,
    currentBikes: 4,
    predictedStock: 4.0,
    pEmpty: 0.1,
  },
  boundary: { legIndex: 1, nodeId: 'ND-221', lat: 37.5665, lng: 126.978 },
  walkLeg: {
    mode: 'WALK',
    fromNodeId: 'ND-221',
    fromNodeName: null,
    fromLat: 37.5665,
    fromLng: 126.978,
    toNodeId: 'ST-ALT-A',
    toNodeName: '교대',
    toLat: 37.5666,
    toLng: 126.978,
    routeId: null,
    routeName: null,
    minutes: 0.2,
    distanceMeters: 14,
    geometry: {
      type: 'MultiLineString',
      coordinates: [
        [
          [126.978, 37.5665],
          [126.978, 37.5666],
        ],
      ],
    },
    geometryStatus: 'estimated',
    estimated: true,
  },
  route: {
    routeType: 'BIKE_SUBWAY',
    totalMinutes: 20.0,
    source: 'ALGORITHM',
    totalDistanceMeters: 6000.0,
    transferCount: 0,
    legs: [
      {
        mode: 'BIKE',
        minutes: 20.0,
        routeId: null,
        fromNodeId: 'ST-ALT-A',
      },
    ],
  },
}

export const rerouteFixtures: Record<RerouteStatus, RerouteCheckResponse> = {
  no_trigger: rerouteNoTriggerFixture,
  no_alternative: rerouteNoAlternativeFixture,
  unavailable: rerouteUnavailableFixture,
  proposal: rerouteProposalFixture,
}

export const mockRerouteRepository: RerouteRepository = {
  async check(request, signal) {
    await delay(160, signal)
    const statusKey = (import.meta.env.VITE_REROUTE_MOCK_STATUS?.trim() ||
      'proposal') as RerouteStatus
    const fixture = rerouteFixtures[statusKey] ?? rerouteFixtures.proposal
    if (fixture.status !== 'proposal') return fixture
    return {
      ...fixture,
      target: fixture.target ? { ...fixture.target, rentalId: request.rentalId } : fixture.target,
      boundary: { ...request.boundary },
      walkLeg: fixture.walkLeg
        ? {
            ...fixture.walkLeg,
            fromNodeId: request.boundary.nodeId,
            fromLat: request.boundary.lat,
            fromLng: request.boundary.lng,
          }
        : fixture.walkLeg,
    }
  },
}
