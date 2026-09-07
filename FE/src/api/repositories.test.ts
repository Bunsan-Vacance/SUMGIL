// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest'
import type { KakaoMaps } from '../lib/kakao/sdk'
import { createKakaoPlaceRepository } from './repositories'

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
})
