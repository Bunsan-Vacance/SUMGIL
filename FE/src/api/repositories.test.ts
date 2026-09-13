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

  it('일반 장소를 역으로 추정하지 않고 안전한 오류를 반환한다', async () => {
    const repository = createBackendRouteRepository('http://be.test')
    await expect(
      repository.search(
        { origin: { ...station('역삼'), stationId: undefined }, destination: station('강변') },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'unsupported-place' })
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
