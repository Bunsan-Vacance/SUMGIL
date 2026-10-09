// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import type { KakaoMaps } from '../lib/kakao/sdk'
import { RepositoryError } from './errors'
import {
  createBackendBikeStationRepository,
  createBackendRouteRepository,
  createBackendStationRepository,
  createKakaoPlaceRepository,
} from './repositories'

function fakeMaps(overrides: Partial<KakaoMaps['services']> = {}): KakaoMaps {
  const point = function (this: { lat: number; lng: number }, lat: number, lng: number) {
    this.lat = lat
    this.lng = lng
  }
  const maps = {
    LatLng: point,
    LatLngBounds: function () {},
    Map: function () {},
    Marker: function () {},
    Polyline: function () {},
    services: {
      Status: { OK: 'OK', ZERO_RESULT: 'ZERO_RESULT', ERROR: 'ERROR' },
      Places: function () {},
      ...overrides,
    },
  } as unknown as KakaoMaps
  return maps
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('카카오 장소 repository', () => {
  it('장소 검색 응답을 화면 장소로 변환하고 좌표와 URL을 검증한다', async () => {
    const keywordSearch = vi.fn((_query, callback) =>
      callback(
        [
          {
            id: '1',
            place_name: '멀티캠퍼스',
            category_group_name: '학교',
            address_name: '서울 강남구',
            road_address_name: '서울 강남구 테헤란로',
            x: '127.1',
            y: '37.5',
            place_url: 'https://place.map.kakao.com/1',
          },
          { id: '2', place_name: '빈 좌표', x: '', y: '37.5' },
          { id: '3', place_name: '잘못된 좌표', x: 'bad', y: '37.5' },
        ],
        'OK',
      ),
    )
    const repository = createKakaoPlaceRepository(async () =>
      fakeMaps({
        Places: class {
          keywordSearch = keywordSearch
        } as unknown as KakaoMaps['services']['Places'],
        Geocoder: class {
          addressSearch = vi.fn()
        } as unknown as KakaoMaps['services']['Geocoder'],
      }),
    )

    await expect(repository.search('멀티캠퍼스', new AbortController().signal)).resolves.toEqual([
      {
        id: '1',
        name: '멀티캠퍼스',
        address: '서울 강남구 테헤란로',
        kind: '학교',
        lat: 37.5,
        lng: 127.1,
        placeUrl: 'https://place.map.kakao.com/1',
      },
    ])
    expect(keywordSearch).toHaveBeenCalledWith('멀티캠퍼스', expect.any(Function))
  })

  it('장소 검색 결과가 없으면 주소 검색으로 재시도한다', async () => {
    const addressSearch = vi.fn((_query, callback) =>
      callback([{ address_name: '서울 강남구 테헤란로 212', x: '127.039', y: '37.501' }], 'OK'),
    )
    const repository = createKakaoPlaceRepository(async () =>
      fakeMaps({
        Places: class {
          keywordSearch = (_query: string, callback: (results: never[], status: string) => void) =>
            callback([], 'ZERO_RESULT')
        } as unknown as KakaoMaps['services']['Places'],
        Geocoder: class {
          addressSearch = addressSearch
        } as unknown as KakaoMaps['services']['Geocoder'],
      }),
    )

    await expect(
      repository.search('테헤란로 212', new AbortController().signal),
    ).resolves.toMatchObject([
      {
        name: '서울 강남구 테헤란로 212',
        address: '서울 강남구 테헤란로 212',
        lat: 37.501,
        lng: 127.039,
      },
    ])
    expect(addressSearch).toHaveBeenCalledOnce()
  })

  it('SDK 오류는 거짓 빈 결과로 바꾸지 않는다', async () => {
    const repository = createKakaoPlaceRepository(async () =>
      fakeMaps({
        Places: class {
          keywordSearch = (_query: string, callback: (results: never[], status: string) => void) =>
            callback([], 'ERROR')
        } as unknown as KakaoMaps['services']['Places'],
        Geocoder: class {
          addressSearch = vi.fn()
        } as unknown as KakaoMaps['services']['Geocoder'],
      }),
    )

    await expect(repository.search('장소', new AbortController().signal)).rejects.toThrow(
      'place-search-failed',
    )
  })

  it('취소된 요청의 늦은 SDK callback은 결과를 반영하지 않는다', async () => {
    let callback!: (results: never[], status: string) => void
    const repository = createKakaoPlaceRepository(async () =>
      fakeMaps({
        Places: class {
          keywordSearch = (_query: string, next: (results: never[], status: string) => void) => {
            callback = next
          }
        } as unknown as KakaoMaps['services']['Places'],
        Geocoder: class {
          addressSearch = vi.fn()
        } as unknown as KakaoMaps['services']['Geocoder'],
      }),
    )
    const request = new AbortController()
    const pending = repository.search('장소', request.signal)
    await Promise.resolve()
    request.abort()
    callback([], 'OK')

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('Kakao 검색 결과에 서버용 역 ID를 추정해서 부여하지 않는다', async () => {
    const keywordSearch = vi.fn((_query, callback) =>
      callback(
        [
          {
            id: 'station',
            place_name: '역삼역 2호선',
            category_group_code: 'SW8',
            category_group_name: '지하철역',
            address_name: '서울 강남구',
            x: '127.036',
            y: '37.501',
          },
          {
            id: 'place',
            place_name: '역삼역 카페',
            category_group_name: '카페',
            address_name: '서울 강남구',
            x: '127.037',
            y: '37.502',
          },
          {
            id: 'exit',
            place_name: '강남역 신분당선 4번출구',
            category_group_code: 'SW8',
            category_group_name: '지하철출구',
            address_name: '서울 강남구',
            x: '127.038',
            y: '37.503',
          },
        ],
        'OK',
      ),
    )
    const repository = createKakaoPlaceRepository(async () =>
      fakeMaps({
        Places: class {
          keywordSearch = keywordSearch
        } as unknown as KakaoMaps['services']['Places'],
        Geocoder: class {
          addressSearch = vi.fn()
        } as unknown as KakaoMaps['services']['Geocoder'],
      }),
    )

    const places = await repository.search('역삼역', new AbortController().signal)
    expect(places).toHaveLength(3)
    expect(places.map((place) => place.id)).toEqual(['station', 'place', 'exit'])
    places.forEach((place) => expect(place).not.toHaveProperty('stationId'))
  })
})

describe('백엔드 repository', () => {
  const station = (id: string) => ({
    id,
    name: id,
    address: '서울',
    kind: '지하철역',
    stationId: id,
  })

  it('역 검색 결과의 숫자 stationId와 환승 노선 정보를 그대로 보존한다', async () => {
    const fetchMock = vi.fn(async () => ({
      status: 200,
      ok: true,
      json: async () => ({
        success: true,
        data: [
          {
            stationId: '208',
            stationName: '왕십리',
            lineId: '1002',
            lineName: '2호선',
            lat: 37.561159,
            lng: 127.035505,
          },
          {
            stationId: '208',
            stationName: '왕십리',
            lineId: '1005',
            lineName: '5호선',
            lat: 37.561159,
            lng: 127.035505,
          },
        ],
      }),
    }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      createBackendStationRepository('http://be.test').search(
        '왕십리역',
        new AbortController().signal,
      ),
    ).resolves.toEqual([
      {
        stationId: '208',
        stationName: '왕십리',
        lineId: '1002',
        lineName: '2호선',
        lat: 37.561159,
        lng: 127.035505,
      },
      {
        stationId: '208',
        stationName: '왕십리',
        lineId: '1005',
        lineName: '5호선',
        lat: 37.561159,
        lng: 127.035505,
      },
    ])
    expect(fetchMock).toHaveBeenCalledWith(
      'http://be.test/api/stations/search?query=%EC%99%95%EC%8B%AD%EB%A6%AC%EC%97%AD',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('역 검색 결과의 영문 stationId도 숫자 ID와 함께 보존한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [
            { stationId: '150', stationName: '서울' },
            { stationId: 'S410', stationName: '서울대벤처타운' },
          ],
        }),
      })),
    )

    await expect(
      createBackendStationRepository('http://be.test').search('서울', new AbortController().signal),
    ).resolves.toEqual([
      { stationId: '150', stationName: '서울' },
      { stationId: 'S410', stationName: '서울대벤처타운' },
    ])
  })

  it('역 검색 결과 stationId가 공백이면 응답을 무효 처리한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [{ stationId: '   ', stationName: '강변' }],
        }),
      })),
    )

    await expect(
      createBackendStationRepository('http://be.test').search('강변', new AbortController().signal),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('역 검색 응답 좌표가 잘못되면 빈 결과로 숨기지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [{ stationId: '214', stationName: '강변', lat: 95, lng: 127 }],
        }),
      })),
    )

    await expect(
      createBackendStationRepository('http://be.test').search('강변', new AbortController().signal),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('새 경로 필드를 보존하고 null 거리와 0회 환승을 구분한다', async () => {
    const payload = {
      routeType: 'SHORTEST',
      totalMinutes: 5,
      source: 'ALGORITHM',
      transferCount: 0,
      totalDistanceMeters: 1234,
      legs: [
        { mode: 'WALK', minutes: 1, distanceMeters: 100 },
        { mode: 'BUS', routeId: 'bus-id', routeName: '740', minutes: 4, distanceMeters: null },
      ],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ success: true, data: [payload] }),
      })),
    )
    const repository = createBackendRouteRepository('http://be.test')
    const request = { origin: station('역삼'), destination: station('강변') }
    const result = await repository.search(request, new AbortController().signal)
    expect(result[0]).toMatchObject({ totalDistanceMeters: 1234, transfers: 0, walk: 100 })
    expect(result[0].legs[1].note).toBe('740')
    expect(result[0].legs[1].distanceMeters).toBeUndefined()
    payload.totalDistanceMeters = -1
    await expect(repository.search(request, new AbortController().signal)).rejects.toMatchObject({
      code: 'invalid-response',
    })
  })

  it('그래프 미적재 503은 재시도 가능한 준비 안내로 구분한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 503,
        json: async () => ({ success: false, error: { code: 'ROUTE_DATA_NOT_READY' } }),
      })),
    )
    await expect(
      createBackendRouteRepository('http://be.test').search(
        { origin: station('역삼'), destination: station('강변') },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({
      code: 'route-data-not-ready',
      status: 503,
      message: '경로 데이터를 준비하고 있어요. 잠시 후 다시 시도해 주세요.',
    })
  })

  it.each([
    [
      'ACCESS_CANDIDATE_NOT_FOUND',
      'access-candidate-not-found',
      '출발지나 도착지 주변에 연결되는 경로가 없어요.',
    ],
    ['OUT_OF_SERVICE_AREA', 'out-of-service-area', '서비스 지역 밖이라 경로를 찾지 못했어요.'],
    ['SERVICE_ENDED', 'service-ended', '선택한 출발 시간에는 이용할 수 없어요.'],
  ] as const)('%s 오류를 복구 가능한 FE 코드로 보존한다', async (serverCode, code, message) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 422,
        json: async () => ({ success: false, error: { code: serverCode } }),
      })),
    )
    await expect(
      createBackendRouteRepository('http://be.test').search(
        { origin: station('역삼'), destination: station('강변') },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ code, message })
  })

  it('경로 응답을 화면 모델로 변환하고 geometry 선을 보존한다', async () => {
    const fetchMock = vi.fn(async () => ({
      status: 200,
      ok: true,
      json: async () => ({
        success: true,
        data: [
          {
            routeType: 'SHORTEST',
            totalMinutes: 11,
            source: 'ALGORITHM',
            legs: [
              {
                mode: 'SUBWAY',
                fromNodeId: '역삼',
                fromNodeName: '역삼',
                fromLat: 37.5,
                fromLng: 127.03,
                toNodeId: '강변',
                toNodeName: '강변',
                toLat: 37.51,
                toLng: 127.04,
                routeId: '1002',
                minutes: 11,
                geometry: {
                  type: 'MultiLineString',
                  coordinates: [
                    [
                      [127.03, 37.5],
                      [127.04, 37.51],
                    ],
                    [
                      [127.05, 37.52],
                      [127.06, 37.53],
                    ],
                  ],
                },
                geometryStatus: 'available',
              },
            ],
          },
        ],
      }),
    }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await createBackendRouteRepository('http://be.test').search(
      {
        origin: station('역삼'),
        destination: station('강변'),
        modes: ['walk', 'subway'],
        priority: 'fast',
        departedAt: '2026-09-11T00:30:00.000Z',
      },
      new AbortController().signal,
    )

    expect(result[0]).toMatchObject({
      minutes: 11,
      line: '2호선',
      modes: ['subway'],
      geometry: { coordinates: expect.arrayContaining([expect.any(Array), expect.any(Array)]) },
    })
    expect(result[0].legs[0].from).toEqual({
      id: '역삼',
      name: '역삼',
      lat: 37.5,
      lng: 127.03,
    })
    expect(result[0].legs[0].to).toEqual({
      id: '강변',
      name: '강변',
      lat: 37.51,
      lng: 127.04,
    })
    expect(result[0].legs[0].geometry?.coordinates).toHaveLength(2)
    expect(result[0].departedAt).toBe('2026-09-11T00:30:00.000Z')
    expect(
      String((fetchMock as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]?.[0]),
    ).toContain(
      'originStationId=%EC%97%AD%EC%82%BC&destStationId=%EA%B0%95%EB%B3%80&modes=WALK%2CSUBWAY&priority=TIME&departureTime=2026-09-11T09%3A30%3A00',
    )
  })

  it('빠른 경로와 다른 경로 응답을 함께 변환하고 자전거 구간 geometry를 보존한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [
            {
              routeType: 'SHORTEST',
              totalMinutes: 11,
              source: 'ALGORITHM',
              legs: [{ mode: 'WALK', minutes: 11 }],
            },
            {
              routeType: 'ALTERNATIVE',
              totalMinutes: 14,
              source: 'ALGORITHM',
              legs: [
                {
                  mode: 'WALK',
                  minutes: 3,
                  geometry: {
                    type: 'MultiLineString',
                    coordinates: [
                      [
                        [127.03, 37.5],
                        [127.031, 37.501],
                      ],
                    ],
                  },
                  geometryStatus: 'available',
                },
                {
                  mode: 'BIKE',
                  minutes: 8,
                  geometry: {
                    type: 'MultiLineString',
                    coordinates: [
                      [
                        [127.031, 37.501],
                        [127.04, 37.51],
                      ],
                    ],
                  },
                  geometryStatus: 'available',
                },
                { mode: 'WALK', minutes: 3 },
              ],
            },
            {
              routeType: 'ALTERNATIVE',
              totalMinutes: 18,
              source: 'ALGORITHM',
              legs: [{ mode: 'WALK', minutes: 18 }],
            },
          ],
        }),
      })),
    )

    const result = await createBackendRouteRepository('http://be.test').search(
      { origin: station('역삼'), destination: station('강변') },
      new AbortController().signal,
    )

    expect(result).toHaveLength(3)
    expect(result.map(({ id, label }) => ({ id, label }))).toEqual([
      { id: 'shortest-0', label: '빠른 경로' },
      { id: 'alternative-1', label: '다른 경로' },
      { id: 'alternative-2', label: '다른 경로' },
    ])
    expect(result[1]).toMatchObject({
      label: '다른 경로',
      modes: ['walk', 'bike'],
      geometry: { coordinates: expect.any(Array) },
    })
    expect(result[2]).toMatchObject({ label: '다른 경로', modes: ['walk'] })
    expect(result[1].legs[0].geometry?.coordinates).toEqual([
      [
        [127.03, 37.5],
        [127.031, 37.501],
      ],
    ])
    expect(result[1].legs[1].geometry?.coordinates).toEqual([
      [
        [127.031, 37.501],
        [127.04, 37.51],
      ],
    ])
  })

  it.each(['station', 'coordinate'] as const)(
    '%s 검색의 COMFORT 요청과 LOW_CONGESTION 응답을 연결한다',
    async (kind) => {
      const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [
            {
              routeType: 'LOW_CONGESTION',
              totalMinutes: 30,
              source: 'ALGORITHM',
              legs: [{ mode: 'SUBWAY', routeId: '1002', minutes: 30 }],
            },
            {
              routeType: 'SHORTEST',
              totalMinutes: 10,
              source: 'ALGORITHM',
              legs: [{ mode: 'SUBWAY', routeId: '1003', minutes: 10 }],
            },
          ],
        }),
      }))
      vi.stubGlobal('fetch', fetchMock)
      const result = await createBackendRouteRepository('http://be.test').search(
        {
          origin:
            kind === 'station'
              ? station('역삼')
              : { id: 'place', name: '카페', address: '', kind: '장소', lat: 37.5, lng: 127.03 },
          destination: { ...station('강변'), lat: 37.535, lng: 127.094 },
          priority: 'calm',
          modes: ['walk', 'subway'],
          departedAt: '2026-09-16T00:30:00Z',
        },
        new AbortController().signal,
      )
      expect(result.map((route) => route.routeType)).toEqual(['LOW_CONGESTION', 'SHORTEST'])
      expect(result[0]).toMatchObject({ label: '다른 경로', minutes: 30 })
      expect(result[0].congestionPrediction).toBeUndefined()
      if (kind === 'station') {
        expect(new URL(fetchMock.mock.calls[0][0]).searchParams.get('priority')).toBe('COMFORT')
      } else {
        expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toMatchObject({
          priority: 'COMFORT',
          departureTime: '2026-09-16T09:30:00',
        })
      }
    },
  )

  it('알 수 없는 경로 유형은 성공 응답으로 숨기지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [
            {
              routeType: 'UNSUPPORTED',
              totalMinutes: 1,
              source: 'ALGORITHM',
              legs: [{ mode: 'WALK', minutes: 1 }],
            },
          ],
        }),
      })),
    )

    await expect(
      createBackendRouteRepository('http://be.test').search(
        { origin: station('역삼'), destination: station('강변') },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('좌표가 없는 장소는 coordinate 요청 전에 오류를 반환한다', async () => {
    const repository = createBackendRouteRepository('http://be.test')
    await expect(
      repository.search(
        { origin: { ...station('역삼'), stationId: undefined }, destination: station('강변') },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-coordinate' })
  })

  it('역이 아닌 장소는 좌표 API에 JSON으로 전달한다', async () => {
    const fetchMock = vi.fn(async () => ({
      status: 501,
      ok: false,
      json: async () => ({
        success: false,
        error: { status: 501, code: 'ACCESS_CANDIDATE_NOT_READY' },
      }),
    }))
    vi.stubGlobal('fetch', fetchMock)
    const origin = {
      id: 'origin-place',
      name: '출발 장소',
      address: '서울',
      kind: '장소',
      lat: 37.5,
      lng: 127.03,
    }
    const destination = {
      id: 'destination-place',
      name: '도착 장소',
      address: '서울',
      kind: '장소',
      lat: 37.51,
      lng: 127.04,
    }

    await expect(
      createBackendRouteRepository('http://be.test').search(
        {
          origin,
          destination,
          modes: ['walk', 'subway'],
          priority: 'fast',
          departedAt: '2026-09-15T00:00:00.000Z',
        },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({
      code: 'coordinate-not-ready',
      status: 501,
      message: '좌표 기반 경로는 아직 준비 중이에요.',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      'http://be.test/api/routes/search/coordinate',
      expect.objectContaining({
        method: 'POST',
        signal: expect.any(AbortSignal),
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({
          origin: { lat: 37.5, lng: 127.03, name: '출발 장소' },
          destination: { lat: 37.51, lng: 127.04, name: '도착 장소' },
          modes: ['WALK', 'SUBWAY'],
          priority: 'TIME',
          departureTime: '2026-09-15T09:00:00',
        }),
      }),
    )
  })

  it('좌표 API의 잘못된 좌표 오류를 사용자 오류로 변환한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 400,
        ok: false,
        json: async () => ({
          success: false,
          error: { status: 400, code: 'INVALID_COORDINATE' },
        }),
      })),
    )

    await expect(
      createBackendRouteRepository('http://be.test').search(
        {
          origin: { ...station('origin'), stationId: undefined, lat: 37.5, lng: 127.03 },
          destination: { ...station('destination'), stationId: undefined, lat: 37.51, lng: 127.04 },
        },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({
      code: 'invalid-coordinate',
      status: 400,
      message: '출발지와 도착지 좌표를 확인해 주세요.',
    })
  })

  it('unavailable geometry는 버리고 transfer를 이동수단·환승 수에 중복 반영하지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [
            {
              routeType: 'SHORTEST',
              totalMinutes: 14,
              source: 'ALGORITHM',
              legs: [
                {
                  mode: 'SUBWAY',
                  fromNodeName: '역삼',
                  toNodeName: '선릉',
                  routeId: '1002',
                  minutes: 5,
                  geometry: {
                    type: 'MultiLineString',
                    coordinates: [
                      [
                        [127.03, 37.5],
                        [127.04, 37.51],
                      ],
                    ],
                  },
                  geometryStatus: 'unavailable',
                },
                {
                  mode: 'TRANSFER',
                  fromNodeName: '선릉',
                  toNodeName: '선릉',
                  routeId: '1002',
                  minutes: 2,
                  geometryStatus: 'unavailable',
                },
                {
                  mode: 'SUBWAY',
                  fromNodeName: '선릉',
                  toNodeName: '강변',
                  routeId: '2080',
                  minutes: 7,
                  geometryStatus: 'unavailable',
                },
              ],
            },
          ],
        }),
      })),
    )
    const result = await createBackendRouteRepository('http://be.test').search(
      { origin: station('역삼'), destination: station('강변') },
      new AbortController().signal,
    )

    expect(result[0]).toMatchObject({ transfers: 1, modes: ['subway'] })
    expect(result[0].geometry).toBeUndefined()
    expect(result[0].legs[0].geometry).toBeUndefined()
  })

  it('알 수 없는 geometryStatus는 성공 응답으로 숨기지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [
            {
              routeType: 'SHORTEST',
              totalMinutes: 1,
              source: 'ALGORITHM',
              legs: [
                {
                  mode: 'SUBWAY',
                  minutes: 1,
                  geometryStatus: 'pending',
                },
              ],
            },
          ],
        }),
      })),
    )
    await expect(
      createBackendRouteRepository('http://be.test').search(
        { origin: station('역삼'), destination: station('강변') },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('구간 endpoint 좌표가 범위를 벗어나면 응답을 무효 처리한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [
            {
              routeType: 'SHORTEST',
              totalMinutes: 1,
              source: 'ALGORITHM',
              legs: [
                {
                  mode: 'SUBWAY',
                  fromNodeName: '역삼',
                  fromLat: 95,
                  fromLng: 127,
                  toNodeName: '강변',
                  toLat: 37.5,
                  toLng: 127.04,
                  routeId: '1002',
                  minutes: 1,
                },
              ],
            },
          ],
        }),
      })),
    )
    await expect(
      createBackendRouteRepository('http://be.test').search(
        { origin: station('역삼'), destination: station('강변') },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('대여소 nearby 응답은 주소 없는 결과를 빈 주소로 만들지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: [
            {
              rentalId: 'ST-1',
              name: '대여소',
              lat: 37.5,
              lng: 127.03,
              dockCount: 12,
              distanceMeters: 49.8,
            },
          ],
        }),
      })),
    )
    await expect(
      createBackendBikeStationRepository('http://be.test').nearby(
        { lat: 37.5, lng: 127.03, radiusMeters: 3000, limit: 100 },
        new AbortController().signal,
      ),
    ).resolves.toEqual([
      {
        id: 'ST-1',
        name: '대여소',
        address: undefined,
        lat: 37.5,
        lng: 127.03,
        dockCount: 12,
        distanceMeters: 49.8,
      },
    ])
  })

  describe('대여소 nearby 재고 필드', () => {
    const nearbyWith = async (extra: Record<string, unknown>) => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => ({
          status: 200,
          ok: true,
          json: async () => ({
            success: true,
            data: [{ rentalId: 'ST-1', name: '대여소', lat: 37.5, lng: 127.03, ...extra }],
          }),
        })),
      )
      return createBackendBikeStationRepository('http://be.test').nearby(
        { lat: 37.5, lng: 127.03 },
        new AbortController().signal,
      )
    }
    const at = '2026-10-09T01:02:03+09:00'

    it('재고와 갱신 시각을 그대로 전달한다', async () => {
      await expect(nearbyWith({ availableBikes: 5, stockUpdatedAt: at })).resolves.toMatchObject([
        { availableBikes: 5, stockUpdatedAt: at },
      ])
    })

    it('필드가 없으면 키를 만들지 않는다', async () => {
      const [station] = await nearbyWith({})
      expect('availableBikes' in station).toBe(false)
      expect('stockUpdatedAt' in station).toBe(false)
    })

    it('재고가 null이면 갱신 시각도 null로 만든다', async () => {
      await expect(nearbyWith({ availableBikes: null, stockUpdatedAt: at })).resolves.toMatchObject(
        [{ availableBikes: null, stockUpdatedAt: null }],
      )
    })

    it.each([-1, 1.5, '3'])('잘못된 재고 %s는 오류다', async (bad) => {
      await expect(nearbyWith({ availableBikes: bad, stockUpdatedAt: at })).rejects.toMatchObject({
        code: 'invalid-response',
      })
    })

    it('잘못된 ISO 시각은 오류다', async () => {
      await expect(nearbyWith({ availableBikes: 3, stockUpdatedAt: '어제' })).rejects.toMatchObject(
        {
          code: 'invalid-response',
        },
      )
    })
  })

  it('대여소 단건 재고 응답을 상태별로 보존한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: {
            rentalId: 'ST-1',
            availableBikes: 0,
            stockUpdatedAt: '2026-09-17T10:00:00+09:00',
            status: 'AVAILABLE',
          },
        }),
      })),
    )
    await expect(
      createBackendBikeStationRepository('http://be.test').stock(
        'ST-1',
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({
      rentalId: 'ST-1',
      availableBikes: 0,
      status: 'AVAILABLE',
    })
  })

  it('총 거치대 수를 optional 필드로 보존하고 기존 응답도 허용한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: {
            rentalId: 'ST-1',
            availableBikes: 4,
            rackCount: 6,
            stockUpdatedAt: '2026-09-17T10:00:00+09:00',
            status: 'AVAILABLE',
          },
        }),
      })),
    )
    await expect(
      createBackendBikeStationRepository('http://be.test').stock(
        'ST-1',
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ rackCount: 6 })

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: {
            rentalId: 'ST-1',
            availableBikes: 4,
            stockUpdatedAt: '2026-09-17T10:00:00+09:00',
            status: 'AVAILABLE',
          },
        }),
      })),
    )
    await expect(
      createBackendBikeStationRepository('http://be.test').stock(
        'ST-1',
        new AbortController().signal,
      ),
    ).resolves.not.toHaveProperty('rackCount')
  })

  it('총 거치대 수가 음수나 소수면 응답을 거부한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: {
            rentalId: 'ST-1',
            availableBikes: 4,
            rackCount: -1,
            stockUpdatedAt: '2026-09-17T10:00:00+09:00',
            status: 'AVAILABLE',
          },
        }),
      })),
    )
    await expect(
      createBackendBikeStationRepository('http://be.test').stock(
        'ST-1',
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: {
            rentalId: 'ST-1',
            availableBikes: 4,
            rackCount: 6.5,
            stockUpdatedAt: '2026-09-17T10:00:00+09:00',
            status: 'AVAILABLE',
          },
        }),
      })),
    )
    await expect(
      createBackendBikeStationRepository('http://be.test').stock(
        'ST-1',
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('대여소 단건 재고의 대여소 ID가 요청과 다르면 거부한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: {
            rentalId: 'ST-2',
            availableBikes: 4,
            stockUpdatedAt: '2026-09-17T10:00:00+09:00',
            status: 'STALE',
          },
        }),
      })),
    )
    await expect(
      createBackendBikeStationRepository('http://be.test').stock(
        'ST-1',
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('UNAVAILABLE 재고는 수량을 지어낸 응답으로 받지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 200,
        ok: true,
        json: async () => ({
          success: true,
          data: {
            rentalId: 'ST-1',
            availableBikes: null,
            stockUpdatedAt: null,
            status: 'UNAVAILABLE',
          },
        }),
      })),
    )
    await expect(
      createBackendBikeStationRepository('http://be.test').stock(
        'ST-1',
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ availableBikes: null, stockUpdatedAt: null, status: 'UNAVAILABLE' })
  })

  it('HTTP 오류와 취소를 빈 성공 결과로 숨기지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 404,
        ok: false,
        json: async () => ({ success: false, error: 'STATION_NOT_FOUND' }),
      })),
    )
    await expect(
      createBackendRouteRepository('http://be.test').search(
        { origin: station('없는역'), destination: station('강변') },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'station-not-found' })

    const controller = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, options: { signal: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            options.signal.addEventListener('abort', () =>
              reject(new DOMException('Aborted', 'AbortError')),
            )
          }),
      ),
    )
    const pending = createBackendBikeStationRepository('http://be.test').nearby(
      { lat: 37.5, lng: 127.03 },
      controller.signal,
    )
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('경로 검색 mock 선택', () => {
  it('API base를 유지한 채 route search mock만 선택한다', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://be.test')
    vi.stubEnv('VITE_ROUTE_SEARCH_MOCK', 'true')
    vi.resetModules()

    try {
      const { isBackendConfigured, isRouteSearchMockEnabled, routeRepository } =
        await import('./repositories')
      expect(isBackendConfigured).toBe(true)
      expect(isRouteSearchMockEnabled).toBe(true)
      const result = await routeRepository.search(
        {
          origin: { id: '222', name: '강남', address: '서울', kind: '역', stationId: '222' },
          destination: { id: '221', name: '역삼', address: '서울', kind: '역', stationId: '221' },
          modes: ['walk', 'subway'],
          priority: 'fast',
          departedAt: '2026-09-15T08:30:00.000Z',
        },
        new AbortController().signal,
      )
      expect(result[0]).toMatchObject({ routeType: 'SHORTEST', minutes: 5 })
    } finally {
      vi.unstubAllEnvs()
      vi.resetModules()
    }
  })
})

describe('주변 역 저장소', () => {
  const station = {
    stationId: '150',
    stationName: '서울',
    lat: 37.55315,
    lng: 126.972533,
    distanceMeters: 180.4,
    lines: [
      { lineId: '1001', lineName: '1호선' },
      { lineId: '1065', lineName: '공항철도' },
    ],
  }
  const stubNearby = (data: unknown) => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ success: true, data }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }
  const nearby = (request = { lat: 37.55, lng: 126.97 }) =>
    createBackendStationRepository('http://be.test').nearby(request, new AbortController().signal)

  it('환승역의 노선 배열을 포함해 주변 역을 매핑한다', async () => {
    stubNearby([station])
    await expect(nearby()).resolves.toEqual([station])
  })

  it('lineName의 null과 빈 문자열은 null로 둔다', async () => {
    stubNearby([
      {
        ...station,
        lines: [
          { lineId: '1001', lineName: null },
          { lineId: '1065', lineName: '' },
        ],
      },
    ])
    const [result] = await nearby()
    expect(result.lines).toEqual([
      { lineId: '1001', lineName: null },
      { lineId: '1065', lineName: null },
    ])
  })

  it('영문자가 섞인 stationId도 그대로 받는다', async () => {
    stubNearby([{ ...station, stationId: 'S410', stationName: '서울대벤처타운' }])
    const [result] = await nearby()
    expect(result.stationId).toBe('S410')
  })

  it.each([
    ['좌표 범위 밖', { lat: 91 }],
    ['음수 거리', { distanceMeters: -1 }],
    ['lines가 배열이 아님', { lines: null }],
    ['lineId가 빈 문자열', { lines: [{ lineId: '', lineName: '2호선' }] }],
    ['stationId가 빈 문자열', { stationId: ' ' }],
  ])('%s이면 invalid-response다', async (_name, override) => {
    stubNearby([{ ...station, ...override }])
    await expect(nearby()).rejects.toMatchObject({ code: 'invalid-response' })
  })

  it('요청 좌표가 올바르지 않으면 호출하지 않고 bad-request다', async () => {
    const fetchMock = stubNearby([])
    await expect(nearby({ lat: Number.NaN, lng: 127 })).rejects.toMatchObject({
      code: 'bad-request',
    })
    await expect(nearby({ lat: 37.5, lng: 181 })).rejects.toMatchObject({ code: 'bad-request' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('radiusMeters와 limit은 값이 있을 때만 쿼리에 넣는다', async () => {
    const fetchMock = stubNearby([])
    await nearby()
    await createBackendStationRepository('http://be.test').nearby(
      { lat: 37.5, lng: 127, radiusMeters: 1000, limit: 20 },
      new AbortController().signal,
    )
    const urls = fetchMock.mock.calls.map((call) => String((call as unknown[])[0]))
    expect(urls[0]).toBe('http://be.test/api/stations/nearby?lat=37.55&lng=126.97')
    expect(urls[1]).toBe(
      'http://be.test/api/stations/nearby?lat=37.5&lng=127&radiusMeters=1000&limit=20',
    )
  })
})
